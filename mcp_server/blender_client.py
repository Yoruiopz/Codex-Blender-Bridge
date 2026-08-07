"""Concurrency-safe localhost client for the Blender add-on transport."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import math
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from .errors import (
    BridgeConnectionError,
    BridgeError,
    BridgeProtocolError,
    BridgeTimeoutError,
)
from .schemas import BridgeRequest, BridgeResponse, JsonValue

LOGGER = logging.getLogger(__name__)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
DEFAULT_TIMEOUT = 30.0
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_MAX_MESSAGE_BYTES = 4 * 1024 * 1024


def validate_loopback_host(host: str) -> str:
    """Return the bridge's single supported IPv4 loopback address."""

    if not isinstance(host, str) or not host.strip():
        raise ValueError("host must be a non-empty string")
    normalized = host.strip()
    lowered = normalized.rstrip(".").lower()
    if lowered == "localhost":
        # The add-on intentionally binds IPv4 loopback. Avoid Windows resolving
        # localhost to ::1 first and reporting a misleading connection failure.
        return DEFAULT_HOST
    if normalized != DEFAULT_HOST:
        raise ValueError(
            f"Refusing Blender bridge host {host!r}; only {DEFAULT_HOST} is allowed"
        )
    return DEFAULT_HOST


def _validate_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535")
    return port


def _validate_timeout(value: float, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0.001
    ):
        raise ValueError(f"{name} must be a finite number of at least 0.001 seconds")
    return float(value)


@dataclass(frozen=True, slots=True)
class ClientConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    timeout: float = DEFAULT_TIMEOUT
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES
    include_timestamps: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "host", validate_loopback_host(self.host))
        object.__setattr__(self, "port", _validate_port(self.port))
        object.__setattr__(self, "timeout", _validate_timeout(self.timeout, "timeout"))
        object.__setattr__(
            self,
            "connect_timeout",
            _validate_timeout(self.connect_timeout, "connect_timeout"),
        )
        if (
            isinstance(self.max_message_bytes, bool)
            or not isinstance(self.max_message_bytes, int)
            or not 1024 <= self.max_message_bytes <= DEFAULT_MAX_MESSAGE_BYTES
        ):
            raise ValueError(
                "max_message_bytes must be an integer from 1024 to 4194304"
            )


class BlenderClient:
    """Async persistent client with ID-correlated concurrent requests.

    One background task owns socket reads. Callers add a future to ``_pending``
    before writing, and the reader resolves the matching future by response ID.
    Writes and connection transitions are independently serialized.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        include_timestamps: bool = True,
    ) -> None:
        self.config = ClientConfig(
            host=host,
            port=port,
            timeout=timeout,
            connect_timeout=connect_timeout,
            max_message_bytes=max_message_bytes,
            include_timestamps=include_timestamps,
        )
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[JsonValue]] = {}
        self._pending_generations: dict[str, int | None] = {}
        self._sent_ids: set[str] = set()
        self._session_generation = 0
        self._reader_generation: int | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    @property
    def host(self) -> str:
        return self.config.host

    @property
    def port(self) -> int:
        return self.config.port

    @property
    def timeout(self) -> float:
        return self.config.timeout

    @property
    def connected(self) -> bool:
        writer = self._writer
        task = self._reader_task
        return bool(
            writer is not None
            and not writer.is_closing()
            and task is not None
            and not task.done()
        )

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def connect(self) -> None:
        """Open the connection if needed; repeated calls are idempotent."""

        async with self._lifecycle_lock:
            if self.connected:
                return
            await self._close_stale_writer()
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self.host,
                        self.port,
                        # The configured cap applies to the JSON payload. Leave
                        # room for either LF or CRLF framing delimiters.
                        limit=self.config.max_message_bytes + 2,
                    ),
                    timeout=self.config.connect_timeout,
                )
            except asyncio.TimeoutError as exc:
                raise BridgeTimeoutError(
                    f"Timed out connecting to Blender at {self.host}:{self.port}",
                    context={"host": self.host, "port": self.port, "executed": False},
                    retryable=True,
                ) from exc
            except (OSError, ConnectionError) as exc:
                raise BridgeConnectionError(
                    f"Could not connect to Blender at {self.host}:{self.port}: {exc}",
                    context={"host": self.host, "port": self.port, "executed": False},
                    retryable=True,
                ) from exc
            self._reader = reader
            self._writer = writer
            self._session_generation += 1
            self._reader_generation = self._session_generation
            self._reader_task = asyncio.create_task(
                self._reader_loop(reader), name="blender-codex-response-reader"
            )
            LOGGER.info("Connected to Blender bridge at %s:%s", self.host, self.port)

    async def disconnect(self) -> None:
        """Close the connection and reject all in-flight requests."""

        await self.close()

    async def close(self) -> None:
        async with self._lifecycle_lock:
            closing_ids = set(self._pending)
            task = self._reader_task
            writer = self._writer
            self._reader_task = None
            self._reader = None
            self._writer = None
            self._reader_generation = None

            current = asyncio.current_task()
            if task is not None and task is not current and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if writer is not None:
                writer.close()
                with contextlib.suppress(OSError, ConnectionError):
                    await writer.wait_closed()
            self._fail_pending(
                lambda request_id: BridgeConnectionError(
                    "Blender bridge connection was closed",
                    context=self._uncertain_context(request_id),
                    request_id=request_id,
                    retryable=request_id not in self._sent_ids,
                ),
                request_ids=closing_ids,
            )

    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        request_id: str | None = None,
    ) -> JsonValue:
        """Send one command and return its result.

        ``request_id`` is injectable for tests and tracing. Production callers
        normally leave it unset and receive a collision-resistant ``req_`` ID.
        """

        operation_timeout = (
            self.timeout
            if timeout is None
            else _validate_timeout(timeout, "request timeout")
        )
        identifier = request_id or f"req_{uuid.uuid4().hex}"
        try:
            request = BridgeRequest.create(
                request_id=identifier,
                method=method,
                params=params,
                include_timestamp=self.config.include_timestamps,
                # A conservative floor prevents Blender's queue deadline from
                # extending even fractionally past the caller's own deadline.
                timeout_ms=math.floor(operation_timeout * 1000.0),
            )
        except ValueError as exc:
            raise BridgeError("INVALID_ARGUMENT", str(exc)) from exc
        payload = json.dumps(
            request.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > self.config.max_message_bytes:
            raise BridgeError(
                "INVALID_ARGUMENT",
                "Request exceeds the configured transport message limit",
                context={
                    "size_bytes": len(payload),
                    "max_bytes": self.config.max_message_bytes,
                },
                request_id=identifier,
            )
        encoded = payload + b"\n"

        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[JsonValue] = loop.create_future()
        # Reserve the ID before the first await. This makes injected duplicate
        # IDs deterministic even when two calls begin while connect() is pending.
        if identifier in self._pending:
            raise ValueError(f"request ID {identifier!r} is already in flight")
        self._pending[identifier] = response_future
        self._pending_generations[identifier] = None
        try:
            await self.connect()
            if response_future.done():
                return await response_future
            self._pending_generations[identifier] = self._reader_generation
            async with self._write_lock:
                writer = self._writer
                if writer is None or writer.is_closing():
                    raise BridgeConnectionError(
                        "Blender bridge disconnected before the request was sent",
                        context={"executed": False},
                        request_id=identifier,
                        retryable=True,
                    )
                self._sent_ids.add(identifier)
                writer.write(encoded)
                await writer.drain()
            try:
                return await asyncio.wait_for(
                    asyncio.shield(response_future), timeout=operation_timeout
                )
            except asyncio.TimeoutError as exc:
                raise BridgeTimeoutError(
                    f"Blender method '{method}' timed out after {operation_timeout:g}s",
                    context={
                        "method": method,
                        "timeout_seconds": operation_timeout,
                        "outcome_unknown": True,
                    },
                    request_id=identifier,
                    retryable=False,
                ) from exc
        except asyncio.CancelledError:
            # A caller abandoning a live future must also abandon the session.
            # Closing the socket lets the add-on atomically cancel work that is
            # still pending; already-running work remains visible in Blender's
            # operation history instead of being silently retried.
            self._pending.pop(identifier, None)
            self._pending_generations.pop(identifier, None)
            if not response_future.done():
                response_future.cancel()
            await self._drop_connection(
                BridgeConnectionError(
                    f"Caller cancelled Blender method '{method}'; connection dropped for safety.",
                    context=self._uncertain_context(identifier),
                    request_id=identifier,
                    retryable=False,
                )
            )
            raise
        except BridgeError:
            raise
        except (OSError, ConnectionError) as exc:
            self._pending.pop(identifier, None)
            self._pending_generations.pop(identifier, None)
            failure = BridgeConnectionError(
                f"Connection failed while calling '{method}': {exc}",
                context=self._uncertain_context(identifier),
                request_id=identifier,
                retryable=identifier not in self._sent_ids,
            )
            await self._drop_connection(failure)
            raise failure from exc
        finally:
            pending = self._pending.get(identifier)
            if pending is response_future:
                self._pending.pop(identifier, None)
            self._pending_generations.pop(identifier, None)
            if not response_future.done():
                response_future.cancel()
            self._sent_ids.discard(identifier)

    async def call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        request_id: str | None = None,
    ) -> JsonValue:
        """Alias used by tool registries and callers that prefer RPC wording."""

        return await self.request(
            method, params, timeout=timeout, request_id=request_id
        )

    async def __aenter__(self) -> BlenderClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _reader_loop(self, reader: asyncio.StreamReader) -> None:
        failure: BridgeError | None = None
        try:
            while True:
                line = await reader.readline()
                if not line:
                    failure = BridgeConnectionError(
                        "Blender bridge closed the connection",
                        retryable=True,
                    )
                    break
                if not line.endswith(b"\n"):
                    failure = BridgeProtocolError(
                        "Blender response frame is not newline terminated"
                    )
                    break
                payload = line[:-1]
                if payload.endswith(b"\r"):
                    payload = payload[:-1]
                if len(payload) > self.config.max_message_bytes:
                    failure = BridgeProtocolError(
                        "Blender response exceeds the configured message limit",
                        context={"max_bytes": self.config.max_message_bytes},
                    )
                    break
                try:
                    decoded = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    failure = BridgeProtocolError(
                        "Blender bridge sent malformed JSON",
                        context={"detail": str(exc)},
                    )
                    break
                try:
                    response = BridgeResponse.from_mapping(decoded)
                except BridgeProtocolError as exc:
                    if exc.request_id and exc.request_id in self._pending:
                        future = self._pending.pop(exc.request_id)
                        self._pending_generations.pop(exc.request_id, None)
                        if not future.done():
                            future.set_exception(exc)
                        continue
                    failure = exc
                    break
                response_future = self._pending.get(response.id)
                if response_future is None:
                    LOGGER.warning(
                        "Ignoring response for unknown or expired request ID %s",
                        response.id,
                    )
                    continue
                self._pending.pop(response.id)
                self._pending_generations.pop(response.id, None)
                self._sent_ids.discard(response.id)
                if response_future.done():
                    continue
                if response.ok:
                    response_future.set_result(response.result)
                else:
                    assert response.error is not None
                    response_future.set_exception(
                        BridgeError(
                            response.error.code,
                            response.error.message,
                            context=response.error.context,
                            retryable=response.error.retryable,
                            request_id=response.id,
                        )
                    )
        except asyncio.CancelledError:
            return
        except (OSError, ConnectionError, ValueError) as exc:
            failure = BridgeConnectionError(
                f"Blender response reader failed: {exc}",
                retryable=True,
            )
        except Exception as exc:  # defensive boundary around a background task
            LOGGER.exception("Unexpected Blender response reader failure")
            failure = BridgeProtocolError(
                "Unexpected Blender response reader failure",
                context={"exception_type": type(exc).__name__},
            )
        finally:
            if failure is not None:
                await self._reader_finished(reader, failure)

    async def _reader_finished(
        self, reader: asyncio.StreamReader, failure: BridgeError
    ) -> None:
        async with self._lifecycle_lock:
            if self._reader is not reader:
                return
            generation = self._reader_generation
            failed_ids = {
                request_id
                for request_id, pending_generation in self._pending_generations.items()
                if pending_generation == generation
            }
            writer = self._writer
            self._reader = None
            self._writer = None
            self._reader_task = None
            self._reader_generation = None
            if writer is not None:
                writer.close()
                with contextlib.suppress(OSError, ConnectionError):
                    await writer.wait_closed()
            self._fail_pending(
                lambda request_id: BridgeError(
                    failure.code,
                    failure.message,
                    context=self._request_failure_context(failure.context, request_id),
                    retryable=(
                        False if request_id in self._sent_ids else failure.retryable
                    ),
                    request_id=request_id,
                ),
                request_ids=failed_ids,
            )
        LOGGER.warning("Blender bridge connection ended: %s", failure.message)

    async def _drop_connection(self, failure: BridgeError) -> None:
        async with self._lifecycle_lock:
            generation = self._reader_generation
            failed_ids = {
                request_id
                for request_id, pending_generation in self._pending_generations.items()
                if pending_generation == generation
            }
            task = self._reader_task
            writer = self._writer
            self._reader_task = None
            self._reader = None
            self._writer = None
            self._reader_generation = None
            if task is not None and task is not asyncio.current_task() and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if writer is not None:
                writer.close()
                with contextlib.suppress(OSError, ConnectionError):
                    await writer.wait_closed()
            self._fail_pending(
                lambda request_id: BridgeError(
                    failure.code,
                    failure.message,
                    context=self._request_failure_context(failure.context, request_id),
                    retryable=(
                        False if request_id in self._sent_ids else failure.retryable
                    ),
                    request_id=request_id,
                ),
                request_ids=failed_ids,
            )

    async def _close_stale_writer(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        self._reader_task = None
        self._reader_generation = None
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, ConnectionError):
                await writer.wait_closed()

    def _fail_pending(
        self,
        factory: Any,
        *,
        request_ids: set[str] | None = None,
    ) -> None:
        selected_ids = set(self._pending) if request_ids is None else request_ids
        for request_id in selected_ids:
            future = self._pending.pop(request_id, None)
            self._pending_generations.pop(request_id, None)
            if future is None:
                continue
            if not future.done():
                future.set_exception(factory(request_id))
            self._sent_ids.discard(request_id)

    def _uncertain_context(self, request_id: str) -> dict[str, bool]:
        if request_id in self._sent_ids:
            return {"outcome_unknown": True}
        return {"executed": False}

    def _request_failure_context(
        self,
        base: Mapping[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        context = {
            key: value
            for key, value in base.items()
            if key not in {"executed", "outcome_unknown"}
        }
        context.update(self._uncertain_context(request_id))
        return context


# A descriptive alias for codebases that name both client variants explicitly.
AsyncBlenderClient = BlenderClient


class SyncBlenderClient:
    """Thread-safe blocking facade over :class:`BlenderClient`.

    A private event loop owns the async client's connection, allowing calls from
    multiple ordinary threads without creating a socket per request.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        include_timestamps: bool = True,
    ) -> None:
        self.config = ClientConfig(
            host=host,
            port=port,
            timeout=timeout,
            connect_timeout=connect_timeout,
            max_message_bytes=max_message_bytes,
            include_timestamps=include_timestamps,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: BlenderClient | None = None
        self._thread: threading.Thread | None = None
        self._start_lock = threading.RLock()
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None

    @property
    def connected(self) -> bool:
        client = self._client
        return client.connected if client is not None else False

    @property
    def is_connected(self) -> bool:
        return self.connected

    def connect(self) -> None:
        self._ensure_thread()
        assert self._client is not None
        self._submit(
            self._client.connect(), timeout=self.config.connect_timeout + 1.0
        )

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        request_id: str | None = None,
    ) -> JsonValue:
        self._ensure_thread()
        assert self._client is not None
        operation_timeout = self.config.timeout if timeout is None else _validate_timeout(timeout, "request timeout")
        return cast(
            JsonValue,
            self._submit(
                self._client.request(
                    method, params, timeout=operation_timeout, request_id=request_id
                ),
                timeout=operation_timeout + self.config.connect_timeout + 1.0,
            ),
        )

    def call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        request_id: str | None = None,
    ) -> JsonValue:
        return self.request(
            method, params, timeout=timeout, request_id=request_id
        )

    def close(self) -> None:
        with self._start_lock:
            loop = self._loop
            client = self._client
            thread = self._thread
            if loop is None or thread is None:
                return
            if client is not None and loop.is_running():
                try:
                    future = asyncio.run_coroutine_threadsafe(client.close(), loop)
                    future.result(timeout=self.config.connect_timeout + 1.0)
                except Exception:
                    LOGGER.debug("Error closing synchronous Blender client", exc_info=True)
            if loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=self.config.connect_timeout + 1.0)
            self._loop = None
            self._client = None
            self._thread = None
            self._ready.clear()

    def __enter__(self) -> SyncBlenderClient:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _ensure_thread(self) -> None:
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready.clear()
            self._startup_error = None
            self._thread = threading.Thread(
                target=self._thread_main,
                name="blender-codex-sync-client",
                daemon=True,
            )
            self._thread.start()
            if not self._ready.wait(timeout=self.config.connect_timeout + 1.0):
                raise BridgeConnectionError("Timed out starting client event loop")
            if self._startup_error is not None:
                raise BridgeConnectionError(
                    f"Could not start client event loop: {self._startup_error}"
                ) from self._startup_error

    def _thread_main(self) -> None:
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._client = BlenderClient(
                self.config.host,
                self.config.port,
                self.config.timeout,
                connect_timeout=self.config.connect_timeout,
                max_message_bytes=self.config.max_message_bytes,
                include_timestamps=self.config.include_timestamps,
            )
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _submit(self, coroutine: Any, *, timeout: float) -> Any:
        loop = self._loop
        if loop is None or not loop.is_running():
            if hasattr(coroutine, "close"):
                coroutine.close()
            raise BridgeConnectionError("Synchronous client event loop is not running")
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise BridgeTimeoutError(
                "Synchronous Blender bridge call exceeded its deadline"
            ) from exc


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_HOST",
    "DEFAULT_MAX_MESSAGE_BYTES",
    "DEFAULT_PORT",
    "DEFAULT_TIMEOUT",
    "AsyncBlenderClient",
    "BlenderClient",
    "ClientConfig",
    "SyncBlenderClient",
    "validate_loopback_host",
]
