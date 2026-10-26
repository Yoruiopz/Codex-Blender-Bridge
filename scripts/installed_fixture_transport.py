"""Persistent, nonblocking-to-caller TCP client for installed native fixtures.

This module is fixture infrastructure. Its worker owns only sockets, JSON and
bounded queues. It never knows about Blender, its runtime or its schedulers.
"""
from __future__ import annotations

import json
import math
import queue
import re
import socket
import threading
import time
from contextlib import suppress
from typing import Any

MAX_FRAME_BYTES = 4 * 1024 * 1024
_METHOD = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_PHASE = re.compile(r"[a-z][a-z0-9_-]{0,47}")


class FixtureTransportError(RuntimeError):
    """A terminal fixture transport failure; requests are never retried."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate response object key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Non-finite JSON response")


class PersistentTCP:
    """One literal-loopback connection, one outstanding request, no caller waits.

    ``submit`` freezes input and returns an independent request copy. ``poll``
    returns None until a correlated terminal response is ready, then a receipt
    containing that request, response and transport label. A failure is terminal.
    ``close`` requests worker shutdown and joins for at most 0.2 seconds; callers
    can observe ``closed`` on subsequent main-thread timer turns.
    """

    def __init__(self, port: int, phase: str, request_timeout: float = 30.0):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Fixture TCP port must be an integer from 1 to 65535")
        if type(phase) is not str or _PHASE.fullmatch(phase) is None:
            raise ValueError("Fixture phase must be a bounded plain identifier")
        if (type(request_timeout) not in (int, float) or not math.isfinite(request_timeout)
                or not 0.001 <= request_timeout <= 300):
            raise ValueError("Fixture request timeout must be finite and from 0.001 to 300 seconds")
        self._port, self._phase, self._timeout = port, phase, float(request_timeout)
        self._commands: queue.Queue = queue.Queue(maxsize=1)
        self._responses: queue.Queue = queue.Queue(maxsize=1)
        self._stop, self._connected, self._finished = (threading.Event() for _ in range(3))
        self._failure: str | None = None
        self._pending: tuple[dict, float] | None = None
        self._sequence = 0
        self._caller_ident = threading.get_ident()
        self._thread = threading.Thread(target=self._worker, name="installed-fixture-tcp", daemon=True)
        self._thread.start()

    @property
    def connected(self) -> bool:
        return self._connected.is_set() and not self._finished.is_set()

    @property
    def closed(self) -> bool:
        return self._finished.is_set()

    @property
    def worker_ident(self) -> int | None:
        return self._thread.ident

    def _caller(self):
        if threading.get_ident() != self._caller_ident:
            raise RuntimeError("Only the creating fixture thread may submit or poll")

    def _record_failure(self, message: str):
        if self._failure is None:
            self._failure = message[:512]
        self._stop.set()

    def _check_available(self):
        if self._failure is not None:
            raise FixtureTransportError(self._failure)
        if self._stop.is_set() or self.closed:
            raise FixtureTransportError("Fixture TCP client is closed or closing")

    def submit(self, method: str, params: dict) -> dict:
        self._caller()
        self._check_available()
        if self._pending is not None:
            raise RuntimeError("Only one fixture request may be pending")
        if type(method) is not str or len(method) > 128 or _METHOD.fullmatch(method) is None:
            raise ValueError("Fixture method must be a bounded dotted tool identifier")
        if type(params) is not dict:
            raise ValueError("Fixture params must be a plain dictionary")
        identifier = self._phase + "-" + str(self._sequence + 1)
        request = {"id": identifier, "method": method, "params": params,
                   "protocol_version": "1.0", "timeout_ms": max(1, int(self._timeout * 1000))}
        payload = json.dumps(request, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_FRAME_BYTES:
            raise ValueError("Fixture request exceeds the 4 MiB frame bound")
        frozen = json.loads(payload)
        deadline = time.monotonic() + self._timeout
        self._commands.put_nowait((frozen, payload + b"\n", deadline))
        self._pending = frozen, deadline
        self._sequence += 1
        return json.loads(payload)

    def poll(self) -> dict[str, Any] | None:
        self._caller()
        self._check_available()
        try:
            response = self._responses.get_nowait()
        except queue.Empty:
            if self._pending is not None and time.monotonic() >= self._pending[1]:
                self._record_failure("Fixture request deadline expired; request was not retried")
                raise FixtureTransportError(self._failure) from None
            return None
        if self._pending is None:
            self._record_failure("Unexpected fixture response without a pending request")
            raise FixtureTransportError(self._failure)
        request = self._pending[0]
        self._pending = None
        return {"request": request, "response": response,
                "transport": "127.0.0.1 persistent TCP; genuine queued main-thread executor"}

    def close(self) -> None:
        self._caller()
        self._stop.set()
        with suppress(queue.Full):
            self._commands.put_nowait(None)
        self._thread.join(timeout=0.2)

    def _receive(self, connection, identifier, deadline):
        buffered = bytearray()
        while not self._stop.is_set():
            if time.monotonic() >= deadline:
                raise FixtureTransportError("Fixture request deadline expired; request was not retried")
            try:
                part = connection.recv(min(65536, MAX_FRAME_BYTES + 3 - len(buffered)))
            except TimeoutError:
                continue
            if not part:
                raise FixtureTransportError("Fixture peer disconnected before the terminal response")
            buffered.extend(part)
            newline = buffered.find(b"\n")
            if newline < 0:
                if len(buffered) > MAX_FRAME_BYTES + 1:
                    raise FixtureTransportError("Fixture response exceeds the 4 MiB frame bound")
                continue
            line = bytes(buffered[:newline])
            if line.endswith(b"\r"):
                line = line[:-1]
            if len(line) > MAX_FRAME_BYTES:
                raise FixtureTransportError("Fixture response exceeds the 4 MiB frame bound")
            if buffered[newline + 1:]:
                raise FixtureTransportError("Unexpected bytes after one fixture terminal response")
            response = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object,
                                  parse_constant=_invalid_constant)
            if (type(response) is not dict or response.get("id") != identifier
                    or response.get("protocol_version") != "1.0" or type(response.get("ok")) is not bool):
                raise FixtureTransportError("Fixture response envelope or request correlation is invalid")
            if response["ok"]:
                if "result" not in response or "error" in response:
                    raise FixtureTransportError("Fixture success response envelope is invalid")
            elif type(response.get("error")) is not dict or "result" in response:
                raise FixtureTransportError("Fixture failure response envelope is invalid")
            return response
        return None

    def _worker(self):
        try:
            with socket.create_connection(("127.0.0.1", self._port),
                                          timeout=min(1.0, self._timeout)) as connection:
                connection.settimeout(min(0.1, self._timeout))
                self._connected.set()
                while not self._stop.is_set():
                    try:
                        command = self._commands.get(timeout=0.02)
                    except queue.Empty:
                        continue
                    if command is None:
                        break
                    request, payload, deadline = command
                    if time.monotonic() >= deadline:
                        raise FixtureTransportError("Fixture request expired before send; request was not retried")
                    connection.sendall(payload)
                    response = self._receive(connection, request["id"], deadline)
                    if response is not None and not self._stop.is_set():
                        self._responses.put_nowait(response)
        except Exception as error:
            if not self._stop.is_set():
                self._record_failure(f"{type(error).__name__}: {error}")
        finally:
            self._finished.set()
