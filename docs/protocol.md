# Blender transport protocol

This document defines the local protocol between the standalone MCP server and the Blender add-on. It is not the MCP protocol itself.

Normative terms **MUST**, **MUST NOT**, **SHOULD**, and **MAY** describe the intended V1 contract. Where the implementation is still partial, unsupported behavior must fail explicitly rather than being emulated.

## Transport

- Transport: TCP.
- Bind address: the literal IPv4 loopback address `127.0.0.1`.
- Framing: newline-delimited JSON (NDJSON).
- Encoding: UTF-8 without a byte-order mark.
- One frame is one complete JSON object followed by `\n`. Receivers SHOULD accept `\r\n`.
- JSON text MUST NOT contain a literal unescaped newline inside a frame.
- Both sides MUST impose a finite frame-size limit and close or reject an oversized frame without attempting unbounded buffering. V1 allows at most 4 MiB (`4 * 1024 * 1024` bytes) of UTF-8 JSON payload; the trailing LF or CRLF delimiter is not counted.
- The add-on MUST NOT fall back to `0.0.0.0`, `::`, a hostname resolving to a non-loopback address, or a LAN address.

TCP provides byte ordering, not message framing; implementations must buffer partial reads and may receive several newline-terminated frames in one read.

## Protocol version

V1 uses the string version:

```json
"1.0"
```

Every request, response, and event includes `protocol_version`. The major component defines compatibility. A peer receiving an unsupported major version returns `UNSUPPORTED_PROTOCOL_VERSION` when the request ID can be recovered, then may close the connection.

Backward-compatible additions within major version 1 may add optional fields, error context, event kinds, methods, or enum values. Receivers MUST ignore unknown optional fields. Removing a field, changing its type/meaning, or changing framing requires a new major version.

The bridge does not currently require a separate handshake. `bridge.status` returns both peer/application version information and is the normal compatibility probe.

## Request envelope

```json
{
  "protocol_version": "1.0",
  "id": "req_01HZX6K9N8Q2",
  "method": "scene.inspect",
  "params": {
    "include_hidden": false,
    "max_objects": 200
  },
  "timestamp": "2026-08-07T20:15:01.125Z"
}
```

Fields:

| Field | Required | Contract |
| --- | --- | --- |
| `protocol_version` | yes | Version string described above. |
| `id` | yes | Non-empty caller-generated string, unique among active requests on that connection. It is opaque and echoed exactly. |
| `method` | yes | Registered dotted tool name. No dynamic Python lookup or import is permitted. |
| `params` | yes | JSON object. Use `{}` when a method has no arguments. |
| `timestamp` | no | RFC 3339 UTC timestamp for diagnostics; it is not used for authorization or deadline calculation. |
| `timeout_ms` | no | Optional positive end-to-end caller budget, capped by local policy. Absence uses the server default. |

String envelope bounds are 256 characters for `id`, 128 for `method`, and 128 for `timestamp`. Tool-specific strings have their own narrower or Blender-defined limits where appropriate. A response whose encoded JSON would exceed the payload cap is replaced by a compact correlated `MESSAGE_TOO_LARGE` failure.

Unknown top-level optional fields are ignored for V1 forward compatibility. Invalid types, a missing required field, a duplicate active ID at the MCP client, or an unknown method produce an explicit failure.

## Successful response

```json
{
  "protocol_version": "1.0",
  "id": "req_01HZX6K9N8Q2",
  "ok": true,
  "timestamp": "2026-08-07T20:15:01.148+00:00",
  "result": {
    "scene": "Scene",
    "objects": [],
    "truncated": false
  }
}
```

Requirements:

- `id` exactly matches the request.
- `ok` is `true`.
- `protocol_version` is the add-on's response protocol version and `timestamp` records response creation in UTC.
- `result` is present and JSON-safe; it may be `null` only when the method contract allows it.
- `error` is absent.
- A mutating tool returns relevant post-operation state and affected-object metadata, not merely `true`.
- Bounded results expose truncation explicitly.

## Error response

```json
{
  "protocol_version": "1.0",
  "id": "req_01HZX6K9N8Q2",
  "ok": false,
  "timestamp": "2026-08-07T20:15:01.148+00:00",
  "error": {
    "code": "OBJECT_NOT_FOUND",
    "message": "Object 'Dragon_Left' does not exist.",
    "context": {
      "available_similar_objects": ["Dragon", "Dragon.Wing.L"]
    },
    "retryable": false
  }
}
```

Requirements:

- `ok` is `false` and `error` is present; `result` is absent.
- `message` is concise, user-safe, and actionable.
- `context`, when present, is a bounded object and must not contain secrets or an unrestricted traceback.
- `retryable`, when present, indicates whether retrying without changing request/user state may plausibly succeed. It is advisory and defaults to `false` when omitted.
- If malformed JSON prevents recovery of `id`, the implementation may use `id: null` for a parse error and then continue or close according to local safety policy.
- One accepted request receives at most one terminal response.

### Error codes

| Code | Meaning | Usually retryable |
| --- | --- | --- |
| `MALFORMED_JSON` | Frame is not valid UTF-8 JSON. | no |
| `INVALID_REQUEST` | Envelope is missing/has invalid fields. | no |
| `UNSUPPORTED_PROTOCOL_VERSION` | Peer major version is unsupported. | no |
| `MESSAGE_TOO_LARGE` | Frame exceeds the 4 MiB transport cap. | with a smaller request |
| `METHOD_NOT_FOUND` | No registered Blender method exists. | no |
| `INVALID_ARGUMENT` | Method parameters fail validation. | no |
| `OBJECT_NOT_FOUND` | Named/stable object reference is absent. | after reinspect |
| `MATERIAL_NOT_FOUND` | Named material is absent. | after reinspect |
| `INVALID_MODE` | Blender mode/context cannot perform the operation. | after context change |
| `INVALID_SELECTION` | Selection is missing, stale, or incompatible. | after reselection |
| `PERMISSION_DENIED` | Blender-side permission is disabled. | after user consent |
| `TOOLSET_DISABLED` | Domain toolset is not enabled. | after enablement |
| `AGENT_PAUSED` | Agent modifications are paused. | yes, after resume |
| `EMERGENCY_STOPPED` | Emergency stop prevents execution. | after explicit reset |
| `BLENDER_CONTEXT_ERROR` | Required area/region/context is unavailable. | context-dependent |
| `OPERATION_FAILED` | Handler failed after validation. | context-dependent |
| `TIMEOUT` | Deadline expired before a terminal result. | context-dependent |
| `NOT_IMPLEMENTED` | Method/option is recognized but unsupported. | no |
| `SERVER_ERROR` | Queue saturation, shutdown, or an unexpected server failure. | context-dependent |

Public codes should remain stable. Method-specific context may include missing permission names, supported modes/options, similar object names, safe limits, or a local diagnostic ID.

## Events

Events reserve a V1-compatible path for progress and lifecycle information. They are non-terminal and correlated where applicable.

```json
{
  "protocol_version": "1.0",
  "type": "event",
  "event": "progress",
  "request_id": "req_01HZX6K9N8Q2",
  "sequence": 1,
  "timestamp": "2026-08-07T20:15:01.600Z",
  "data": {
    "stage": "capturing",
    "completed": 1,
    "total": 3,
    "message": "Capturing front view"
  }
}
```

Event fields:

- `type` is always `event`.
- `event` is a stable event kind such as `progress`, `log`, `state_changed`, or `checkpoint_created`.
- `request_id` is present for request-scoped events and absent/null for connection-wide events.
- `sequence` increases monotonically within one request so clients can order progress.
- `data` is a bounded JSON object.

Events never replace the terminal response. A client must determine request completion only from the matching success/error response. The current MVP emits no events and its client is not required to consume them. Event emission must not be enabled until both peers recognize event envelopes; event-capable clients then ignore unknown event kinds. Callers must not require progress events in V1.

## Timeouts and cancellation

Timeouts exist at several layers:

1. MCP tool deadline.
2. MCP-server/Blender-client request deadline.
3. Add-on queue-wait/execution deadline.
4. Socket read/connect timeouts used for lifecycle detection.

The effective request budget is the smallest configured applicable deadline. `timeout_ms`, if accepted, is capped by policy and starts when the MCP server dispatches the Blender request. Queue wait consumes this budget.

An expired command that has not started MUST be removed/rejected without mutation. For an active Blender operation, a caller timeout does **not** imply rollback: most Blender calls cannot be safely interrupted at arbitrary bytecode points. Handlers should be short; future long-running handlers need explicit cooperative safe points and cancellation semantics.

If a response arrives after the MCP caller has timed out, the Blender client discards it for correlation purposes and logs the late result. A mutation that may have completed must remain visible in operation history so the next agent action reinspects state. IDs are not immediately reused.

Caller cancellation closes the shared client connection. The add-on then atomically cancels requests that are still pending and fails the other in-flight calls; a Blender operation that had already crossed the running boundary is not interrupted and remains visible in operation history. The next call reconnects and must reinspect state.

Only a failure known to occur before a frame was sent carries `executed:false` and may be marked `retryable:true`. A timeout, cancellation, disconnect, or malformed response after sending carries `outcome_unknown:true` where an error can be returned and is never automatically retryable.

## Concurrency and ordering

- Multiple requests may be in flight at the transport/client layer.
- Writes on each socket are serialized so NDJSON frames never interleave.
- The Blender main-thread executor processes one command at a time in queue order for the MVP.
- The current add-on queue accepts at most 256 pending commands; saturation returns `SERVER_ERROR` rather than growing without bound.
- Completion order can differ from submission order only if a request is rejected/expired before execution or a future implementation adds explicitly concurrent read paths.
- Callers MUST NOT issue dependent mutations concurrently. A later call should use the verified terminal result of the earlier call.
- Duplicate active IDs are rejected. IDs may be reused only after the previous lifecycle is fully retired, but globally unique IDs are recommended.
- Request order across separate TCP connections is undefined. The MVP should prefer one active MCP bridge connection unless multi-client ownership is explicitly implemented.

## Connection lifecycle

1. The Blender user starts the bridge from the add-on panel.
2. The add-on validates the configured literal loopback host, binds, and begins listening.
3. The MCP server connects on demand or startup.
4. `bridge.status` verifies application/protocol versions and current Blender state.
5. Requests flow until either side closes.
6. Disconnect fails unresolved requests with a connection error; it does not stop Blender.
7. Add-on stop/unregister rejects new work, resolves queued requests, closes sockets, and removes its main-thread timer.

Reconnect does not make old selection IDs, pending requests, or connection-scoped state valid. Codex should re-run status/selection inspection.

## Method naming and parameters

Methods use lowercase dotted names:

```text
domain.verb
```

Examples: `scene.inspect`, `transform.translate`, `checkpoint.create`.

Parameter rules:

- Use JSON objects, never positional arrays at the method boundary.
- Distinguish omitted values from explicit `null` only when the schema defines that distinction.
- Reject unknown parameters by default for mutating tools; read tools may adopt explicitly documented forward-compatible behavior.
- Bound strings, arrays, image sizes, traversal depth, pagination limits, and numeric ranges.
- Object references must be explicit names or opaque IDs defined by a tool schema. Never treat input as Python code.

## Serialization conventions

- JSON finite numbers only; `NaN` and infinities are errors or become documented `null`/warning fields.
- Vectors are fixed-length arrays in XYZ order unless named otherwise.
- Matrices, if exposed, state row/column and coordinate-space conventions in their schema.
- Programmatic rotations use radians unless a field explicitly ends in `_degrees`.
- Times are RFC 3339 UTC strings.
- Paths are strings only for tools with external-file/save permission and must be normalized by Blender.
- Binary images are not embedded without a strict size policy. A capture result identifies a bounded artifact representation and its MIME type, dimensions, view, shading, and restoration status.

## Representative calls

Read-only selection inspection:

```json
{"protocol_version":"1.0","id":"req_101","method":"selection.inspect","params":{}}
```

Permission denial:

```json
{"protocol_version":"1.0","id":"req_102","method":"object.delete","params":{"object_name":"Cube"}}
{"protocol_version":"1.0","timestamp":"2026-08-08T12:00:00+00:00","id":"req_102","ok":false,"error":{"code":"PERMISSION_DENIED","message":"Blender-side permission denied.","context":{"required":["DELETE_OBJECTS"],"missing_permissions":["DELETE_OBJECTS"]},"retryable":false}}
```

Post-state from a transform:

```json
{
  "protocol_version": "1.0",
  "timestamp": "2026-08-08T12:00:01+00:00",
  "id": "req_103",
  "ok": true,
  "result": {
    "changed": true,
    "object": "Key_Light",
    "location": [0.0, 0.0, 4.5],
    "rotation_mode": "XYZ",
    "rotation_euler": [0.0, 0.0, 0.0],
    "rotation_quaternion": [1.0, 0.0, 0.0, 0.0],
    "scale": [1.0, 1.0, 1.0],
    "dimensions": [0.0, 0.0, 0.0],
    "matrix_world": [
      [1.0, 0.0, 0.0, 0.0],
      [0.0, 1.0, 0.0, 0.0],
      [0.0, 0.0, 1.0, 4.5],
      [0.0, 0.0, 0.0, 1.0]
    ],
    "operation": {
      "operation_id": "op_42",
      "undo_boundary_created": true
    }
  }
}
```

## Security requirements

- Do not place authentication secrets in messages; the V1 TCP transport is local only.
- Never expose the socket using port forwarding, a reverse proxy, container publish flags, or public host binding.
- Dispatch only registered methods. Never use `eval`, `exec`, arbitrary attribute traversal, or shell interpolation.
- Validate paths and permissions in Blender, even if MCP already validated them.
- Treat every local request as untrusted input for parser, type, range, and size purposes.

See [`security.md`](security.md) for the complete threat model and [`tool-design.md`](tool-design.md) for method-level contracts.
