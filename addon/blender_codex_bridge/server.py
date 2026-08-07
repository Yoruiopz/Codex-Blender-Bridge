"""Localhost-only threaded NDJSON server that only enqueues Blender work."""

from __future__ import annotations

import logging
import queue
import socket
import socketserver
import threading
import time
from contextlib import suppress
from typing import Any

from .command_queue import QueuedRequest
from .constants import DEFAULT_REQUEST_TIMEOUT_SECONDS
from .errors import BridgeError, ErrorCode
from .protocol import Request, Response, decode_request, encode_response
from .selection import clear_selection_references
from .serialization import loads
from .state import BridgeState
from .transport import normalize_loopback_host, read_frame, validate_port

LOGGER = logging.getLogger(__name__)
_STOP_WRITER = object()


def _recover_request_id(frame: bytes | None) -> str | None:
    """Best-effort correlation for a structurally invalid JSON request."""

    if frame is None:
        return None
    try:
        value = loads(frame)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    candidate = value.get("id")
    if not isinstance(candidate, str):
        return None
    return candidate


class _RequestHandler(socketserver.StreamRequestHandler):
    server: _LocalTCPServer

    def setup(self) -> None:
        super().setup()
        if not self.server.register_connection(self.request):
            with suppress(OSError):
                self.request.shutdown(socket.SHUT_RDWR)
            raise ConnectionError("Bridge listener is stopping")
        clear_selection_references()
        self.request.settimeout(self.server.socket_read_timeout)
        self._outbound: queue.Queue[Response | QueuedRequest | object] = queue.Queue(
            maxsize=512
        )
        self._inflight: list[QueuedRequest] = []
        self._active_ids: set[str] = set()
        self._inflight_lock = threading.Lock()
        self._writer = threading.Thread(
            target=self._write_responses,
            name=f"BlenderCodexBridgeWriter-{id(self):x}",
            daemon=True,
        )
        self._writer.start()
        self.server.bridge_state.client_connected()
        LOGGER.info("Bridge client connected from %s", self.client_address[0])

    def finish(self) -> None:
        disconnect_error = BridgeError(
            ErrorCode.SERVER_ERROR,
            "Client disconnected before Blender began executing the request.",
            {"executed": False},
        )
        with self._inflight_lock:
            inflight = list(self._inflight)
        for queued in inflight:
            queued.cancel_pending(disconnect_error)
        with suppress(queue.Full):
            self._outbound.put_nowait(_STOP_WRITER)
        self._writer.join(timeout=2.0)
        self.server.unregister_connection(self.request)
        self.server.bridge_state.client_disconnected()
        LOGGER.info("Bridge client disconnected from %s", self.client_address[0])
        super().finish()

    def handle(self) -> None:
        while True:
            request_id: str | None = None
            frame: bytes | None = None
            try:
                frame = read_frame(self.rfile)
                if frame is None:
                    return
                request = decode_request(frame)
                request_id = request.id
                timeout = self.server.request_timeout
                if request.timeout_ms is not None:
                    timeout = min(timeout, request.timeout_ms / 1000.0)
                LOGGER.info("Received bridge method %s (%s)", request.method, request.id)
                with self._inflight_lock:
                    if request.id in self._active_ids:
                        raise BridgeError(
                            ErrorCode.INVALID_REQUEST,
                            "Request ID is already active on this connection.",
                            {"duplicate_id": request.id},
                        )
                    self._active_ids.add(request.id)
                try:
                    queued = self.server.submit(request, timeout)
                except Exception:
                    with self._inflight_lock:
                        self._active_ids.discard(request.id)
                    raise
                with self._inflight_lock:
                    self._inflight.append(queued)
                # Continue ingesting frames while a single writer waits for
                # ordered responses. Every request's queue deadline therefore
                # starts when its frame arrives, not after an earlier slow call.
                self._outbound.put(queued)
            except TimeoutError:
                with self._inflight_lock:
                    if self._inflight:
                        # A writer may legitimately be waiting for an active
                        # Blender operation longer than the idle read timeout.
                        continue
                return
            except BridgeError as error:
                if error.code in {
                    ErrorCode.MESSAGE_TOO_LARGE.value,
                    ErrorCode.INVALID_REQUEST.value,
                } and frame is None and request_id is None:
                    # read_frame did not consume a trustworthy complete frame.
                    # Closing avoids parsing the oversized line's remainder as
                    # additional requests.
                    return
                if request_id is None:
                    request_id = _recover_request_id(frame)
                if "duplicate_id" in error.context:
                    # Keep the accepted request's ID unique on the wire. The
                    # rejected duplicate remains explicit in error context.
                    request_id = None
                self._outbound.put(Response.failure(request_id, error))
            except (ConnectionError, OSError):
                return
            except Exception as exc:
                LOGGER.exception("Unhandled bridge connection failure")
                self._outbound.put(
                    Response.failure(
                        request_id,
                        BridgeError(
                            ErrorCode.SERVER_ERROR,
                            "Local bridge server failed to process the request.",
                            {"exception_type": type(exc).__name__},
                        ),
                    ),
                )

    def _write_responses(self) -> None:
        while True:
            work = self._outbound.get()
            try:
                if work is _STOP_WRITER:
                    return
                if isinstance(work, QueuedRequest):
                    remaining = max(0.0, work.deadline - time.monotonic())
                    try:
                        response = work.wait(
                            remaining + 0.25,
                            running_grace=self.server.running_grace,
                        )
                    except BridgeError as error:
                        response = Response.failure(work.request.id, error)
                else:
                    assert isinstance(work, Response)
                    response = work
                try:
                    encoded = encode_response(response)
                except BridgeError as error:
                    # Never write an unbounded result. Replace it with a compact
                    # correlated protocol error that the MCP client can surface.
                    encoded = encode_response(Response.failure(response.id, error))
                self.wfile.write(encoded)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                with suppress(OSError):
                    self.request.shutdown(socket.SHUT_RDWR)
                return
            finally:
                if isinstance(work, QueuedRequest):
                    with self._inflight_lock:
                        if work in self._inflight:
                            self._inflight.remove(work)
                        self._active_ids.discard(work.request.id)
                self._outbound.task_done()


class _LocalTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        submit: Any,
        state: BridgeState,
        request_timeout: float,
    ) -> None:
        self._submit = submit
        self.bridge_state = state
        self.request_timeout = request_timeout
        self.running_grace = max(60.0, request_timeout * 10.0)
        self.socket_read_timeout = max(60.0, request_timeout * 2.0)
        self._connection_lock = threading.Lock()
        self._connections: set[socket.socket] = set()
        self._accepting_requests = True
        super().__init__(address, _RequestHandler, bind_and_activate=True)

    def submit(self, request: Request, timeout: float) -> QueuedRequest:
        with self._connection_lock:
            if not self._accepting_requests:
                raise BridgeError(ErrorCode.SERVER_ERROR, "Bridge listener is stopping.")
            # Keep the lifecycle gate and the fast queue insertion atomic.
            # Runtime shutdown cancels the queue only after deactivate() has
            # acquired this lock, so no accepted request can enqueue afterward.
            return self._submit(request, timeout=timeout)

    def register_connection(self, connection: socket.socket) -> bool:
        with self._connection_lock:
            if not self._accepting_requests:
                return False
            self._connections.add(connection)
            return True

    def unregister_connection(self, connection: socket.socket) -> None:
        with self._connection_lock:
            self._connections.discard(connection)

    def deactivate(self) -> None:
        """Atomically reject submissions and wake every accepted handler."""

        with self._connection_lock:
            self._accepting_requests = False
            connections = list(self._connections)
        for connection in connections:
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)


class LocalBridgeServer:
    """Lifecycle wrapper for a daemon-thread localhost listener."""

    def __init__(self, *, submit: Any, state: BridgeState) -> None:
        self._submit = submit
        self._state = state
        self._server: _LocalTCPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    def start(
        self,
        host: str,
        port: int,
        *,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> tuple[str, int]:
        if self.running:
            assert self._server is not None
            return self._server.server_address
        host = normalize_loopback_host(host)
        port = validate_port(port)
        if not 0.5 <= request_timeout <= 300.0:
            raise BridgeError(
                ErrorCode.INVALID_ARGUMENT,
                "Request timeout must be between 0.5 and 300 seconds.",
            )
        try:
            server = _LocalTCPServer(
                (host, port),
                submit=self._submit,
                state=self._state,
                request_timeout=float(request_timeout),
            )
        except OSError as exc:
            raise BridgeError(
                ErrorCode.SERVER_ERROR,
                f"Could not start the Blender bridge at {host}:{port}.",
                {"detail": str(exc)},
            ) from exc
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="BlenderCodexBridgeServer",
            daemon=True,
        )
        self._server = server
        self._thread = thread
        thread.start()
        bound_host, bound_port = server.server_address
        self._state.set_server(True, bound_host, bound_port)
        LOGGER.info("Blender Codex Bridge listening on %s:%s", bound_host, bound_port)
        return bound_host, bound_port

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.deactivate()
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._state.set_server(False)
        LOGGER.info("Blender Codex Bridge stopped")
