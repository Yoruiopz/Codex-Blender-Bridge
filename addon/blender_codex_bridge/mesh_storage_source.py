"""Private source, ownership and measured-preservation boundary for B2.

Logical readback can tag/unshare existing native storage. This module does not
claim physical cache passivity, a Python sandbox, or a reversible materializer.
"""
from __future__ import annotations

import hashlib
import importlib
import math
from array import array
from types import (
    CodeType,
    FunctionType,
    GetSetDescriptorType,
    MappingProxyType,
    MemberDescriptorType,
    MethodDescriptorType,
    MethodType,
    ModuleType,
    WrapperDescriptorType,
)

from . import current_pixels_graph as graph
from . import mesh_storage_contract as contract
from . import mesh_storage_prepare as primitive
from .native_save_profile import available_memory_facts
from .request_lifecycle import ConnectionLifetime, RequestLifetime
from .scene_job_reservations import TURN_METHOD
from .task_plans import get_task_plans
from .tool_registry import CheckpointAdmissionBinding, ToolContext, check_final_mutation
from .tools import _scene_checkpoint_roles as checkpoint_roles
from .tools import _scene_mutation as checkpoint_proof

# Keep CPython's standard cache binding stable before the first source seal.
# This is not an authority table or an exemption from namespace identity checks.
__warningregistry__ = {}

BASE_MEMORY = 64 * 1024**2
MAX_IMAGES = 8
MAX_IMAGE_PIXELS = 16_777_216
MAX_AGGREGATE_PIXELS = 33_554_432
MAX_MATERIALS = 32


class SourceSeal(tuple):
    """Held immutable source facts; verify never calls an unverified helper."""
    __slots__ = ()

    @classmethod
    def capture(cls, *, inspection=False):
        names = ("mesh_storage_source", "mesh_storage_contract", "mesh_storage_effects", "tools._mesh_storage_job",
                 # check_affected keeps its defining globals even when imported
                 # into tools.mesh_storage. Pin its directly reached helpers
                 # before a permission provider can replace those bindings.
                 "tools.mesh_storage", "tools.artist_loop", "tools._animation_scope", "errors",
                 "tools._scene_checkpoint_roles", "tools._scene_mutation", "entry_effects",
                 "native_save_profile", "state", "permissions", "task_plans", "tool_registry",
                 "request_lifecycle", "scene_jobs", "scene_job_authority", "executor", "command_queue",
                 "checkpoints", "checkpoint_completion", "current_pixels_graph", "mesh_storage_prepare", "uv_edit_guard")
        if inspection:
            names += ("tools._mesh_storage_inspection", "scene_job_reservations", "runtime", "glb_stage_runtime")
        modules = tuple(importlib.import_module(__package__ + "." + name) for name in names)
        module_rows, class_rows, functions, builtins = [], [], [], []
        for module in modules:
            namespace = ModuleType.__getattribute__(module, "__dict__")
            if len(namespace) > 4096 or any(type(key) is not str for key in namespace):
                raise contract.refused("STORAGE_SOURCE_NAMESPACE")
            module_rows.append((module, tuple(namespace.items())))
            for value in namespace.values():
                values = (value,) if type(value) is FunctionType else ()
                if type(value) is type:
                    fields = type.__dict__["__dict__"].__get__(value)
                    if any(type(key) is not str for key in fields):
                        raise contract.refused("STORAGE_SOURCE_CLASS_NAMESPACE")
                    module_name = fields.get("__module__")
                    if type(module_name) is not str or module_name != module.__name__:
                        continue
                    class_rows.append((value, type.__dict__["__mro__"].__get__(value), tuple(fields.items())))
                    values = tuple(fn for item in fields.values() for fn in (
                        (item,) if type(item) is FunctionType else
                        (item.__func__,) if type(item) is classmethod or type(item) is staticmethod else
                        tuple(fn for fn in (item.fget, item.fset, item.fdel) if fn is not None) if type(item) is property else ()))
                for fn in values:
                    keywords = fn.__kwdefaults__
                    if keywords is not None and (type(keywords) is not dict or any(type(k) is not str for k in keywords)):
                        raise contract.refused("STORAGE_SOURCE_KEYWORDS")
                    functions.append((fn, fn.__code__, fn.__globals__, fn.__defaults__, keywords,
                                      () if keywords is None else tuple(keywords.items()),
                                      tuple((cell, cell.cell_contents) for cell in fn.__closure__ or ())))
                    table = fn.__builtins__
                    if not any(table is old for old, _ in builtins):
                        if type(table) is not dict or any(type(k) is not str for k in table):
                            raise contract.refused("STORAGE_SOURCE_BUILTINS")
                        builtins.append((table, tuple(table.items())))
        from .request_lifecycle import threading
        event_kind = threading.Event
        event_fields = type.__dict__["__dict__"].__get__(event_kind)
        class_rows.append((event_kind, type.__dict__["__mro__"].__get__(event_kind), tuple(event_fields.items())))
        for fn in event_fields.values():
            if type(fn) is FunctionType:
                keywords = fn.__kwdefaults__
                functions.append((fn, fn.__code__, fn.__globals__, fn.__defaults__, keywords,
                                  () if keywords is None else tuple(keywords.items()),
                                  tuple((cell, cell.cell_contents) for cell in fn.__closure__ or ())))
        # Namespace rows above retain every alias. Repeated aliases need only
        # one owner fact, but inconsistent snapshots must still refuse capture.
        unique_classes, unique_functions = {}, {}
        for row in class_rows:
            previous = unique_classes.get(id(row[0]))
            if previous is None:
                unique_classes[id(row[0])] = row
                continue
            fields = dict(previous[2])
            if (row[0] is not previous[0] or row[1] is not previous[1]
                    or len(row[2]) != len(fields)
                    or any(type(key) is not str or key not in fields or fields[key] is not value
                           for key, value in row[2])):
                raise contract.refused("STORAGE_SOURCE_CHANGED")
        for row in functions:
            previous = unique_functions.get(id(row[0]))
            if previous is None:
                unique_functions[id(row[0])] = row
                continue
            if (any(row[index] is not previous[index] for index in range(5))
                    or len(row[5]) != len(previous[5]) or len(row[6]) != len(previous[6])
                    or any(type(key) is not str for key, _ in previous[5])):
                raise contract.refused("STORAGE_SOURCE_CHANGED")
            keywords = dict(previous[5])
            if (any(type(key) is not str or key not in keywords or keywords[key] is not value
                    for key, value in row[5])
                    or any(cell is not old_cell or value is not old_value
                           for (cell, value), (old_cell, old_value) in zip(row[6], previous[6], strict=True))):
                raise contract.refused("STORAGE_SOURCE_CHANGED")
        class_rows, functions = list(unique_classes.values()), list(unique_functions.values())
        failure = contract.refused("STORAGE_SOURCE_CHANGED")
        native = (type, len, dict, str, FunctionType, ModuleType.__getattribute__,
                  type.__dict__["__dict__"].__get__, type.__dict__["__mro__"].__get__, failure)
        native += (ModuleType, event_kind)
        watches = []
        for module, name in ((graph, "BUILDS"), (graph, "_REGISTERED_TARGETS"),
                             (primitive, "COLLECTION_BINDING_PINS"), (primitive, "_VALUE_CLASSES"),
                             (checkpoint_proof, "RUNTIME_FIXED")):
            value = vars(module)[name]
            if type(value) is not dict or len(value) > 4096:
                raise contract.refused("STORAGE_SOURCE_CONSTANT_SHAPE")
            for key, item in value.items():
                if ((type(key) is not str and type(key) is not bytes and type(key) is not tuple)
                        or (type(key) is tuple and any(type(part) is not str for part in key))
                        or (type(item) is not str and type(item) is not tuple)
                        or (type(item) is tuple and any(type(part) is not str and type(part) is not int for part in item))):
                    raise contract.refused("STORAGE_SOURCE_CONSTANT_SHAPE")
            watches.append((value, tuple(value.items())))
        # Keep nested policy identities as well as their leaves: an in-place
        # descriptor-policy change must fail before the next native getter.
        runtime = checkpoint_proof.RUNTIME
        if type(runtime) is not dict or any(type(key) is not str or type(value) is not dict for key, value in runtime.items()):
            raise contract.refused("STORAGE_SOURCE_CONSTANT_SHAPE")
        nested = []
        for key, value in runtime.items():
            if any(type(name) is not str or type(kind) is not str for name, kind in value.items()):
                raise contract.refused("STORAGE_SOURCE_CONSTANT_SHAPE")
            nested.append((key, value, tuple(value.items())))
        codes = {}
        pending = [row[1] for row in functions]
        while pending:
            code = pending.pop()
            if id(code) in codes:
                continue
            if len(codes) >= 16384:
                raise contract.refused("STORAGE_SOURCE_CODE_BUDGET")
            codes[id(code)] = code
            pending.extend(value for value in code.co_consts if type(value) is CodeType)
        verify = SourceSeal.__dict__["verify"]
        verify_fact = (verify, verify.__code__, verify.__globals__, verify.__defaults__, verify.__kwdefaults__, verify.__closure__)
        return tuple.__new__(cls, (tuple(module_rows), tuple(class_rows), tuple(functions), tuple(builtins), native,
                                  tuple(watches), MappingProxyType(codes), verify_fact, (runtime, tuple(nested))))

    def verify(self):
        raw_get = ().__class__.__getitem__
        rows, classes, functions, tables, native = raw_get(self, 0), raw_get(self, 1), raw_get(self, 2), raw_get(self, 3), raw_get(self, 4)
        kind, length, dict_type, str_type, fn_type, module_dict, class_dict, class_mro, failure, module_type = native[:10]
        runtime, nested = raw_get(self, 8)
        if kind(runtime) is not dict_type or length(runtime) != length(nested):
            raise failure
        for key in runtime:
            if kind(key) is not str_type:
                raise failure
        for name, table, saved in nested:
            if (name not in runtime or runtime[name] is not table or kind(table) is not dict_type
                    or length(table) != length(saved)):
                raise failure
            for key in table:
                if kind(key) is not str_type:
                    raise failure
            for key, value in saved:
                if key not in table or table[key] is not value:
                    raise failure
        for table, saved in tables:
            if kind(table) is not dict_type or length(table) != length(saved):
                raise failure
            for key in table:
                if kind(key) is not str_type:
                    raise failure
            for key, value in saved:
                if key not in table or table[key] is not value:
                    raise failure
        for module, saved in rows:
            if kind(module) is not module_type:
                raise failure
            fields = module_dict(module, "__dict__")
            if length(fields) != length(saved):
                raise failure
            for key in fields:
                if kind(key) is not str_type:
                    raise failure
            for key, value in saved:
                if key not in fields or fields[key] is not value:
                    raise failure
        for owner, mro, saved in classes:
            if kind(owner) is not kind:
                raise failure
            fields = class_dict(owner)
            if class_mro(owner) is not mro or length(fields) != length(saved):
                raise failure
            for key in fields:
                if kind(key) is not str_type:
                    raise failure
            for key, value in saved:
                if key not in fields or fields[key] is not value:
                    raise failure
        for fn, code, namespace, defaults, keywords, items, closure in functions:
            if (kind(fn) is not fn_type or fn.__code__ is not code or fn.__globals__ is not namespace
                    or fn.__defaults__ is not defaults or fn.__kwdefaults__ is not keywords):
                raise failure
            if keywords is not None:
                if kind(keywords) is not dict_type or length(keywords) != length(items):
                    raise failure
                for key in keywords:
                    if kind(key) is not str_type:
                        raise failure
                for key, value in items:
                    if key not in keywords or keywords[key] is not value:
                        raise failure
            current = fn.__closure__ or ()
            if length(current) != length(closure):
                raise failure
            for index, (cell, value) in enumerate(closure):
                if current[index] is not cell:
                    raise failure
                try:
                    if cell.cell_contents is not value:
                        raise failure
                except ValueError:
                    raise failure from None
        bytes_type, tuple_type = b"".__class__, ().__class__
        for table, saved in raw_get(self, 5):
            if kind(table) is not dict_type or length(table) != length(saved):
                raise failure
            for key in table:
                if kind(key) is not str_type and kind(key) is not bytes_type and kind(key) is not tuple_type:
                    raise failure
                if kind(key) is tuple_type:
                    for part in key:
                        if kind(part) is not str_type:
                            raise failure
            for key, value in saved:
                if key not in table or table[key] is not value:
                    raise failure

    def fingerprint(self):
        return contract.digest({"bindings": [(module.__name__, [(name, id(value)) for name, value in rows])
                                for module, rows in tuple.__getitem__(self, 0)],
                                "functions": [(id(row[0]), id(row[1]), id(row[3]), id(row[4]))
                                              for row in tuple.__getitem__(self, 2)]})


def verify_seal(seal):
    """Prove the held verifier before its first dispatch; no global callback."""
    raw = ().__class__.__getitem__
    fact, native = raw(seal, 7), raw(seal, 4)
    function, code, namespace, defaults, keywords, closure = fact
    kind, failure = raw(native, 0), raw(native, 8)
    if (kind(function) is not raw(native, 4) or function.__code__ is not code
            or function.__globals__ is not namespace or function.__defaults__ is not defaults
            or function.__kwdefaults__ is not keywords or function.__closure__ is not closure):
        raise failure
    function(seal)


def _callback_fact(value, seal, *, internal=False):
    if value is None:
        return None
    if type(value) is FunctionType:
        function, owner = value, None
    elif type(value) is MethodType:
        function, owner = value.__func__, value.__self__
    else:
        raise contract.refused("STORAGE_CONTEXT_CALLBACK_UNQUALIFIED")
    if internal and tuple.__getitem__(seal, 6).get(id(function.__code__)) is not function.__code__:
        raise contract.refused("STORAGE_CONTEXT_CALLBACK_UNQUALIFIED")
    keywords = function.__kwdefaults__
    if keywords is not None and (type(keywords) is not dict or any(type(key) is not str for key in keywords)):
        raise contract.refused("STORAGE_CONTEXT_CALLBACK_UNQUALIFIED")
    return (value, function, owner, function.__code__, function.__globals__, function.__defaults__, keywords,
            () if keywords is None else tuple(keywords.items()),
            tuple((cell, cell.cell_contents) for cell in function.__closure__ or ()))


def _check_callback(value, fact):
    if fact is None:
        if value is not None:
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        return
    original, function, owner, code, namespace, defaults, keywords, items, cells = fact
    if value is not original:
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    if type(value) is MethodType:
        if value.__self__ is not owner or value.__func__ is not function:
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
    elif type(value) is not FunctionType:
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    closure = function.__closure__ or ()
    if (function.__code__ is not code or function.__globals__ is not namespace
            or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords
            or len(closure) != len(cells)):
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    if keywords is not None and (type(keywords) is not dict or len(keywords) != len(items)
            or any(type(key) is not str for key in keywords)
            or any(name not in keywords or keywords[name] is not item for name, item in items)):
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    try:
        if any(actual is not cell or actual.cell_contents is not item
               for actual, (cell, item) in zip(closure, cells, strict=True)):
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
    except ValueError:
        raise contract.refused("STORAGE_CONTEXT_CHANGED") from None


_CONTEXT_FIELDS = ("registry", "state", "permissions", "checkpoints", "jobs", "request_lifecycle", "request_id",
                   "check_cancelled", "check_final_request", "check_final_job", "checkpoint_admission",
                   "checkpoint_call_id", "checkpoint_method", "checkpoint_params", "exclusive_mutation_lease")
_BINDING_FIELDS = ("context", "method", "params", "call_id", "callback", "frozen_params", "readonly_callback",
                   "native_push_callback", "registry", "spec", "enclosing", "active", "stopped", "marker_write_callback")


def _context_slot(owner, kind, name):
    """Read one canonical Python slot without a user attribute callback."""
    if type(owner) is not kind:
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    descriptor = type.__dict__["__dict__"].__get__(kind).get(name)
    if (type(descriptor) is not MemberDescriptorType or descriptor.__objclass__ is not kind
            or descriptor.__name__ != name):
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    return descriptor.__get__(owner, kind)


def capture_context(context, seal):
    """Capture scheduler-owned identities BEFORE any permission provider.

    Event values deliberately remain live. A new canonical Scene context is
    adopted only through an admission's separately verified pre-provider proof.
    """
    verify_seal(seal)
    if type(context) is not ToolContext:
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    fields = {name: ToolContext.__dict__[name].__get__(context, ToolContext) for name in _CONTEXT_FIELDS}
    rows = tuple((name, fields.get(name)) for name in _CONTEXT_FIELDS)
    callbacks = tuple((name, _callback_fact(fields.get(name), seal, internal=name != "check_cancelled"))
                      for name in ("check_cancelled", "check_final_request", "check_final_job"))
    binding = fields.get("checkpoint_admission")
    binding_rows, binding_callbacks = (), ()
    if binding is not None:
        if type(binding) is not CheckpointAdmissionBinding:
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        binding_rows = tuple((name, _context_slot(binding, CheckpointAdmissionBinding, name)) for name in _BINDING_FIELDS)
        binding_callbacks = tuple((name, _callback_fact(_context_slot(binding, CheckpointAdmissionBinding, name), seal, internal=True))
                                  for name in ("readonly_callback", "native_push_callback", "marker_write_callback"))
    lifetime, lifetime_rows, connection_rows, event_rows = fields.get("request_lifecycle"), (), (), []
    if lifetime is not None:
        if type(lifetime) is not RequestLifetime:
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        lifetime_rows = tuple((name, _context_slot(lifetime, RequestLifetime, name)) for name in ("connection", "deadline", "delivered", "rejected"))
        connection = _context_slot(lifetime, RequestLifetime, "connection")
        events = [_context_slot(lifetime, RequestLifetime, name) for name in ("delivered", "rejected")]
        if connection is not None:
            if type(connection) is not ConnectionLifetime:
                raise contract.refused("STORAGE_CONTEXT_CHANGED")
            connection_rows = tuple((name, _context_slot(connection, ConnectionLifetime, name)) for name in ("disconnected", "background_active"))
            events += [_context_slot(connection, ConnectionLifetime, name) for name in ("disconnected", "background_active")]
        for event in events:
            event_kind = type(event)
            if event_kind is not tuple.__getitem__(seal, 4)[10]:
                raise contract.refused("STORAGE_CONTEXT_CHANGED")
            namespace = type.__dict__["__dict__"].__get__(event_kind)
            if len(namespace) > 256 or any(type(name) is not str for name in namespace):
                raise contract.refused("STORAGE_CONTEXT_CHANGED")
            descriptor = namespace.get("__dict__")
            if type(descriptor) is not GetSetDescriptorType or descriptor.__objclass__ is not event_kind:
                raise contract.refused("STORAGE_CONTEXT_CHANGED")
            data = descriptor.__get__(event, event_kind)
            if type(data) is not dict or any(type(name) is not str for name in data):
                raise contract.refused("STORAGE_CONTEXT_CHANGED")
            if type(data.get("_flag")) is not bool or "is_set" in data:
                raise contract.refused("STORAGE_CONTEXT_CHANGED")
            methods = tuple((name, _callback_fact(fn, seal)) for name, fn in namespace.items() if type(fn) is FunctionType)
            event_rows.append((event, event_kind, tuple(namespace.items()), methods, descriptor,
                               tuple((name, item) for name, item in data.items() if name != "_flag")))
    from .permissions import PermissionManager
    from .scene_job_authority import SceneJobPermissions
    permission_rows = []
    manager = fields["permissions"]
    for _ in range(4):
        if type(manager) is not PermissionManager and type(manager) is not SceneJobPermissions:
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        descriptor = type(manager).__dict__["__dict__"]
        data = descriptor.__get__(manager, type(manager))
        if type(data) is not dict or any(type(name) is not str for name in data):
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        names = ("base", "service") if type(manager) is SceneJobPermissions else ("_source",)
        saved = tuple((name, data.get(name)) for name in names)
        provider = None if type(manager) is SceneJobPermissions else _callback_fact(data.get("_source"), seal)
        permission_rows.append((manager, type(manager), descriptor, saved, provider))
        if type(manager) is PermissionManager:
            break
        manager = data["base"]
    else:
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    return (context, seal, rows, callbacks, binding, binding_rows, binding_callbacks,
            lifetime, lifetime_rows, connection_rows, tuple(event_rows), tuple(permission_rows))


def verify_context(context, proof):
    verify_seal(tuple.__getitem__(proof, 1))
    _verify_context_fields(context, proof)


def _verify_context_fields(context, proof):
    """Callback-free fields only; callers hold a freshly verified source seal."""
    (original, _seal, rows, callbacks, binding, binding_rows, binding_callbacks, lifetime, lifetime_rows,
     connection_rows, events, permissions) = proof
    if context is not original or type(context) is not ToolContext:
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    fields = {name: ToolContext.__dict__[name].__get__(context, ToolContext) for name in _CONTEXT_FIELDS}
    if any(fields.get(name) is not value for name, value in rows):
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    for name, fact in callbacks:
        _check_callback(fields.get(name), fact)
    if binding is not None:
        if any(_context_slot(binding, CheckpointAdmissionBinding, name) is not value for name, value in binding_rows):
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        for name, fact in binding_callbacks:
            _check_callback(_context_slot(binding, CheckpointAdmissionBinding, name), fact)
    if lifetime is not None:
        if any(_context_slot(lifetime, RequestLifetime, name) is not value for name, value in lifetime_rows):
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        connection = _context_slot(lifetime, RequestLifetime, "connection")
        if any(_context_slot(connection, ConnectionLifetime, name) is not value for name, value in connection_rows):
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
    for event, event_kind, saved, methods, descriptor, data_rows in events:
        namespace = type.__dict__["__dict__"].__get__(event_kind)
        if (type(event) is not event_kind or len(namespace) != len(saved)
                or any(type(name) is not str for name in namespace)
                or any(name not in namespace or namespace[name] is not value for name, value in saved)):
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        for name, fact in methods:
            _check_callback(namespace[name], fact)
        data = descriptor.__get__(event, event_kind)
        if (type(data) is not dict or len(data) != len(data_rows) + 1 or any(type(name) is not str for name in data)
                or type(data.get("_flag")) is not bool or any(data.get(name) is not value for name, value in data_rows)):
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
    for manager, expected_kind, descriptor, saved, provider in permissions:
        if type(manager) is not expected_kind:
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        data = descriptor.__get__(manager, expected_kind)
        if (type(data) is not dict or any(type(name) is not str for name in data)
                or any(data.get(name) is not value for name, value in saved)):
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        if provider is not None:
            _check_callback(data.get("_source"), provider)


def _same_context_snapshot_data(left, right):
    """Compare immutable snapshot data; never validate current object state."""
    if left is right:
        return True
    return (type(left) is tuple and type(right) is tuple and len(left) == len(right)
            and all(_same_context_snapshot_data(a, b) for a, b in zip(left, right, strict=True)))


def _canonical_inspection_context_data(context, seal, fresh):
    """Reuse equivalent captured DATA after the caller's original fresh capture.

    Current validation remains mandatory on every Gate entry. Unknown admission
    kinds, malformed snapshots and differing baselines keep the fresh snapshot.
    Native slot reads cannot dispatch foreign attribute or descriptor callbacks.
    """
    if (type(context) is not ToolContext or type(fresh) is not tuple or len(fresh) != 12
            or fresh[0] is not context or fresh[1] is not seal):
        return fresh
    missing = object()
    def slot(value, kind, name):
        if type(value) is not kind:
            return missing
        descriptor = type.__dict__["__dict__"].__get__(kind).get(name)
        if (type(descriptor) is not MemberDescriptorType or descriptor.__objclass__ is not kind
                or descriptor.__name__ != name):
            return missing
        return descriptor.__get__(value, kind)
    binding = slot(context, ToolContext, "checkpoint_admission")
    if type(binding) is not CheckpointAdmissionBinding:
        return fresh
    callback = slot(binding, CheckpointAdmissionBinding, "callback")
    if slot(binding, CheckpointAdmissionBinding, "context") is not context:
        return fresh
    for module, _saved in tuple.__getitem__(seal, 0):
        namespace = ModuleType.__getattribute__(module, "__dict__")
        function = namespace.get("_inspection_gate_pure")
        if type(function) is not FunctionType or function.__globals__ is not namespace:
            continue
        kind = namespace.get("_InspectionTurnAdmission")
        if type(kind) is not type or type(callback) is not kind:
            return fresh
        if slot(callback, kind, "context") is not context:
            return fresh
        candidate = slot(callback, kind, "inspection_context_proof")
        if (type(candidate) is not tuple or len(candidate) != 12
                or candidate[0] is not context or candidate[1] is not seal):
            return fresh
        return candidate if _same_context_snapshot_data(fresh, candidate) else fresh
    return fresh


class Gate(tuple):
    """Native tuple entry slots precede every replaceable Python callback."""
    __slots__ = ()

    def __new__(cls, context, source_seal, method=contract.START):
        verify = SourceSeal.__dict__["verify"]
        pure = Gate.__dict__["pure"]
        def facts(fn):
            return (fn, fn.__code__, fn.__globals__, fn.__defaults__, fn.__kwdefaults__, fn.__closure__)
        cell = {"context": context, "registry": context.registry, "state": context.state,
                "floor": BASE_MEMORY, "last_available": 0, "provider_reads": 0,
                "epoch": get_task_plans(context.state).evidence_epoch, "method": method,
                "context_proof": capture_context(context, source_seal)}
        cell["context_proof"] = _canonical_inspection_context_data(context, source_seal, cell["context_proof"])
        return tuple.__new__(cls, (cell, source_seal, facts(verify), facts(pure)))

    @property
    def context(self):
        return tuple.__getitem__(self, 0)["context"]

    @context.setter
    def context(self, context):
        seal = tuple.__getitem__(self, 1)
        verify_seal(seal)
        from .scene_jobs import (
            _InspectionAdmission,
            _InspectionTurnAdmission,
            _StartAdmission,
            _TurnAdmission,
        )
        binding = context.checkpoint_admission
        callback = None if binding is None else binding.callback
        if type(callback) is _StartAdmission or type(callback) is _TurnAdmission:
            proof = callback.storage_context_proof
            if proof is None:
                raise contract.refused("STORAGE_CANONICAL_CONTEXT_REQUIRED")
            verify_context(context, proof)
        elif type(callback) is _InspectionAdmission or type(callback) is _InspectionTurnAdmission:
            proof = callback.inspection_context_proof
            if proof is None:
                raise contract.refused("STORAGE_CANONICAL_CONTEXT_REQUIRED")
            verify_context(context, proof)
        else:
            cell = tuple.__getitem__(self, 0)
            if context is not cell["context"]:
                raise contract.refused("STORAGE_CANONICAL_CONTEXT_REQUIRED")
            verify_context(context, cell["context_proof"])
        cell = tuple.__getitem__(self, 0)
        cell["context"], cell["context_proof"] = context, capture_context(context, seal)
        cell["context_proof"] = _canonical_inspection_context_data(context, seal, cell["context_proof"])

    @property
    def floor(self):
        return tuple.__getitem__(self, 0)["floor"]

    @floor.setter
    def floor(self, value):
        tuple.__getitem__(self, 0)["floor"] = value

    @property
    def last_available(self):
        return tuple.__getitem__(self, 0)["last_available"]

    def pure(self):
        raw_get = ().__class__.__getitem__
        seal, fact = raw_get(self, 1), raw_get(self, 2)
        function, code, namespace, defaults, keywords, closure = fact
        native = raw_get(seal, 4)
        kind, failure = raw_get(native, 0), raw_get(native, 8)
        if (kind(function) is not raw_get(native, 4) or function.__code__ is not code
                or function.__globals__ is not namespace or function.__defaults__ is not defaults
                or function.__kwdefaults__ is not keywords or function.__closure__ is not closure):
            raise failure
        function(seal)  # SourceSeal.verify is held and proved BEFORE dispatch.
        cell = raw_get(self, 0)
        if kind(cell) is not raw_get(native, 2) or len(cell) != 9 or any(kind(key) is not str for key in cell):
            raise failure
        context = cell["context"]
        # Dispatch from the held, just-verified module object. A fresh import
        # could otherwise follow a replaced sys.modules/package alias.
        for module, _saved in raw_get(seal, 0):
            namespace = ModuleType.__getattribute__(module, "__dict__")
            candidate = namespace.get("_inspection_gate_pure")
            if type(candidate) is FunctionType and candidate.__globals__ is namespace:
                if candidate(self, seal, cell):
                    return
                break
        verify_context(context, cell["context_proof"])
        if type(context) is not ToolContext or context.registry is not cell["registry"] or context.state is not cell["state"]:
            raise contract.refused("STORAGE_RUNTIME_CONTEXT_CHANGED")
        method = context.checkpoint_method or (TURN_METHOD if context.check_final_job is not None else cell["method"])
        check_final_mutation(context, method)
        if get_task_plans(cell["state"]).evidence_epoch != cell["epoch"]:
            raise contract.refused("STORAGE_TASK_PLAN_CHANGED")
        facts = available_memory_facts()
        available = facts["available_memory_bytes"]
        if type(available) is not int or available < cell["floor"]:
            raise contract.refused("STORAGE_LIVE_MEMORY_REFUSED")
        cell["last_available"] = available
        check_final_mutation(context, method)

    def authorize(self):
        raw_get = ().__class__.__getitem__
        fact = raw_get(self, 3)
        function, code, namespace, defaults, keywords, closure = fact
        seal = raw_get(self, 1)
        native = raw_get(seal, 4)
        kind, failure = raw_get(native, 0), raw_get(native, 8)
        if (kind(function) is not raw_get(native, 4) or function.__code__ is not code
                or function.__globals__ is not namespace or function.__defaults__ is not defaults
                or function.__kwdefaults__ is not keywords or function.__closure__ is not closure):
            raise failure
        function(self)
        cell = raw_get(self, 0)
        context = cell["context"]
        context.require(*contract.PERMISSIONS)
        # No self/global helper lookup after an arbitrary permission provider.
        if (kind(function) is not raw_get(native, 4) or function.__code__ is not code
                or function.__globals__ is not namespace or function.__defaults__ is not defaults
                or function.__kwdefaults__ is not keywords or function.__closure__ is not closure):
            raise failure
        function(self)
        cell["provider_reads"] += 1


def build_plan(bpy, parameters, gate, origin, *, selected=None):
    gate.pure()
    plan = primitive.build_plan(bpy, parameters.object_name, parameters.mesh_name,
        parameters.attribute_names if selected is None else selected, origin=origin,
        available_memory_bytes=gate.last_available)
    if not all(row.action in {"MATERIALIZE_SINGLE", "NOOP_ALREADY_ARRAY"} for row in plan.targets):
        raise contract.refused("STORAGE_SELECTED_ATTRIBUTE_UNSUPPORTED")
    gate.floor = max(BASE_MEMORY, dict(plan.resources)["required_available_memory_bytes"])
    gate.pure()
    return plan


def metadata_matches(actual, initial, completed):
    """Compare to a computed forward state; never adopt observed metadata."""
    expected = initial.plain()
    expected["attributes"] = [tuple((*row[:5], "ARRAY", *row[6:])) if row[0] in completed else row
                              for row in expected["attributes"]]
    if actual.obj is not initial.obj or actual.mesh is not initial.mesh or actual.plain() != expected:
        raise contract.refused("STORAGE_FORWARD_METADATA_CHANGED")


def _checkpoint_descriptor_error(facts):
    """Attach only already-read bounded builtin facts; no failure-time RNA."""
    error = contract.refused("STORAGE_CHECKPOINT_RUNTIME_DESCRIPTOR_CHANGED")
    cached = {}
    for key, value in facts.items():
        if type(key) is not str or len(key) > 64:
            continue
        if (value is None or type(value) is bool
                or (type(value) is str and len(value) <= 256)
                or (type(value) is int and -(2**63) <= value < 2**63)):
            cached[key] = value
    error.context["checkpoint_descriptor"] = cached
    return error


def _checkpoint_native_keys(keys):
    """Catch only the held native keys invocation, outside both control gates."""
    try:
        return keys(), None
    except TypeError as error:
        return None, error


class _CheckpointRoleAccess:
    """B2-only checked native reads; shared Scene readers stay unchanged."""
    __slots__ = ("_origin", "array_type", "base", "bpy", "check", "collection_getter", "collection_type", "getter", "pointer", "struct_type", "types")

    def __init__(self, bpy, check):
        self.bpy, self.check = bpy, check
        def load(owner, name):
            check()
            value = getattr(owner, name)
            check()
            return value
        self.types = load(bpy, "types")
        self.base = load(self.types, "bpy_struct")
        self.getter = graph._class_find(self.base, "__getattribute__")
        self.pointer = graph._class_find(self.base, "as_pointer")
        self.array_type = load(self.types, "bpy_prop_array")
        self.struct_type = load(self.types, "Struct")
        self.collection_type = load(self.types, "bpy_prop_collection")
        self.collection_getter = graph._class_find(self.collection_type, "__getattribute__")
        if (type(self.getter) is not WrapperDescriptorType or self.getter.__objclass__ is not self.base
                or self.getter.__name__ != "__getattribute__"
                or type(self.pointer) is not MethodDescriptorType or self.pointer.__objclass__ is not self.base
                or self.pointer.__name__ != "as_pointer"
                or not any(parent is self.base for parent in graph._class_mro(self.struct_type))
                or graph._class_find(self.struct_type, "__getattribute__") is not self.getter
                or graph._class_find(self.struct_type, "as_pointer") is not self.pointer):
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_ORIGIN_CHANGED")
        self._origin = tuple((name, getattr(self, name)) for name in self.__slots__ if name != "_origin")

    def call(self, function, *args):
        origin = self._origin
        check = self.check
        for stage in range(3):
            if self._origin is not origin or any(object.__getattribute__(self, name) is not value for name, value in origin):
                raise contract.refused("STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED")
            if stage == 0 or stage == 2:
                check()
            else:
                result = function(*args)
        if self._origin is not origin or any(object.__getattribute__(self, name) is not value for name, value in origin):
            raise contract.refused("STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED")
        return result

    def raw(self, owner, name):
        cls = type(owner)
        # Reject a Python property before dispatch, even though the held native
        # getter would otherwise be available. Metadata classes are also checked.
        descriptor = graph._class_find(cls, name)
        own_rna = name == "bl_rna" and type(descriptor) is self.struct_type
        if name == "bl_rna" and self.call(getattr, self.types, "Struct") is not self.struct_type:
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_STRUCT_CHANGED")
        if not (own_rna or (name in {"user_map", "user_of_id"} and type(descriptor) is MethodDescriptorType
                and descriptor.__name__ == name
                and any(descriptor.__objclass__ is base for base in graph._class_mro(cls)))):
            graph._unshadowed(cls, (name,))
        if (graph._class_find(cls, "__getattribute__") is not self.getter
                or graph._class_find(cls, "__getattr__") is not None
                or graph._class_find(cls, "as_pointer") is not self.pointer):
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_ORIGIN_CHANGED")
        return self.call(self.getter, owner, name)

    def key(self, owner):
        if owner is None:
            return None
        if graph._class_find(type(owner), "as_pointer") is not self.pointer:
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_ORIGIN_CHANGED")
        return graph._int(self.call(self.pointer, owner), 2**64 - 1, minimum=1)

    def token(self, owner):
        pointer = self.key(owner)
        if owner is None:
            return pointer, None
        try:
            uid = self.raw(owner, "session_uid")
        except AttributeError:
            self.call(tuple)
            return pointer, None
        return pointer, graph._int(uid, 2**64 - 1, minimum=1)

    def bounded(self, values, maximum, label):
        iterator = self.call(iter, values)
        result = []
        for _ in range(maximum + 1):
            try:
                item = self.call(next, iterator)
            except StopIteration:
                self.call(tuple)
                return tuple(result)
            result.append(item)
        raise checkpoint_proof.unsupported("Checkpoint " + label + " exceeds its bounded profile.")

    def active(self, layer):
        objects = self.raw(layer, "objects")
        canonical = self.call(getattr, self.types, "LayerObjects")
        rna = graph._class_dict(canonical).get("bl_rna")
        props = self.bounded(self.raw(rna, "properties"), 512, "LayerObjects descriptors")
        prop = next((item for item in props if self.raw(item, "identifier") == "active"), None)
        if (prop is None or self.raw(prop, "type") != "POINTER" or self.raw(prop, "is_runtime")
                or self.raw(prop, "is_registered")
                or self.raw(self.raw(prop, "fixed_type"), "identifier") != "Object"
                or type(objects) is not self.collection_type
                or type(self.collection_getter) is not WrapperDescriptorType
                or self.collection_getter.__objclass__ not in (self.collection_type, object)
                or self.collection_getter.__name__ != "__getattribute__"
                or graph._class_find(self.collection_type, "__getattribute__") is not self.collection_getter):
            raise contract.refused("STORAGE_CHECKPOINT_ACTIVE_COLLECTION_CHANGED")
        graph._unshadowed(self.collection_type, ("active",))
        return self.call(self.collection_getter, objects, "active")

    def lookup(self, collection, name):
        descriptor = graph._class_find(self.collection_type, "get")
        if (type(collection) is not self.collection_type or type(descriptor) is not MethodDescriptorType
                or descriptor.__objclass__ is not self.collection_type or descriptor.__name__ != "get"):
            raise contract.refused("STORAGE_CHECKPOINT_MAIN_COLLECTION_CHANGED")
        return self.call(descriptor, collection, name)

    def identity(self, owner, kind):
        # Identity proves the requested native ID type and actual identity
        # fields. Full logical/schema protection remains the graph pass; its
        # unread declarations are not this Scene role reader's settings scope.
        canonical = self.call(getattr, self.types, kind)
        if type(owner) is not canonical:
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_OWNER_CHANGED")
        rna = self.raw(owner, "bl_rna")
        canonical_rna = graph._class_dict(canonical).get("bl_rna")
        if (type(rna) is not self.struct_type or type(canonical_rna) is not self.struct_type
                or self.raw(rna, "identifier") != kind or self.key(rna) != self.key(canonical_rna)):
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_SCHEMA_CHANGED")
        return (("kind", kind), ("name", graph._text(self.raw(owner, "name"))),
                ("pointer", format(self.key(owner), "x")),
                ("session_uid", str(graph._int(self.raw(owner, "session_uid"), 2**64 - 1, minimum=1))))

    def screen_static_metadata(self, owner):
        """Keep raw()'s unused-field refusals without reading their C values.

        Every actual is_runtime read still uses raw()/call() and their original
        before/after controls. Screen both sides so a native-return callback
        cannot install an identifier/type shadow before the next inspection.
        This retains no metadata, class proof or owner value between reads.
        """
        origin = self._origin
        if self._origin is not origin or any(object.__getattribute__(self, name) is not value for name, value in origin):
            raise contract.refused("STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED")
        cls = type(owner)
        graph._unshadowed(cls, ("identifier", "type"))
        if (graph._class_find(cls, "__getattribute__") is not self.getter
                or graph._class_find(cls, "__getattr__") is not None
                or graph._class_find(cls, "as_pointer") is not self.pointer):
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_ORIGIN_CHANGED")
        if self._origin is not origin or any(object.__getattribute__(self, name) is not value for name, value in origin):
            raise contract.refused("STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED")

    def descriptors(self, owner):
        rna = self.raw(owner, "bl_rna")
        identifier = self.raw(rna, "identifier")
        canonical = self.call(getattr, self.types, identifier)
        if type(owner) is not canonical:
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_OWNER_CHANGED")
        canonical_rna = graph._class_dict(canonical).get("bl_rna")
        # Native wrappers may differ while referring to the same StructRNA.
        if canonical_rna is not rna and (canonical_rna is None or self.key(canonical_rna) != self.key(rna)):
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_SCHEMA_CHANGED")
        properties = self.bounded(self.raw(rna, "properties"), 512, "RNA descriptors")
        allowed = checkpoint_proof.RUNTIME.get(identifier, {})
        for prop in properties:
            self.screen_static_metadata(prop)
            runtime = self.raw(prop, "is_runtime")
            self.screen_static_metadata(prop)
            if type(runtime) is not bool:
                raise _checkpoint_descriptor_error({"owner_identifier": identifier, "is_runtime": runtime})
            if runtime:
                name, kind = self.raw(prop, "identifier"), self.raw(prop, "type")
                expected = allowed.get(name)
                facts = {"owner_identifier": identifier, "property": name, "observed_kind": kind,
                         "expected_kind": expected, "is_runtime": runtime}
                if expected != kind:
                    raise _checkpoint_descriptor_error(facts)
                readonly = self.raw(prop, "is_readonly")
                facts.update(readonly=readonly, expected_readonly=name != "active_selection_set")
                if readonly is not (name != "active_selection_set"):
                    raise _checkpoint_descriptor_error(facts)
                registered = self.raw(prop, "is_registered")
                facts["registered"] = registered
                if registered:
                    raise _checkpoint_descriptor_error(facts)
                if name == "active_selection_set":
                    array_length = self.raw(prop, "array_length")
                    facts["array_length"] = array_length
                    if array_length:
                        raise _checkpoint_descriptor_error(facts)
                    default = self.raw(prop, "default")
                    facts["default"] = default
                    if default != 0:
                        raise _checkpoint_descriptor_error(facts)
                if kind in {"POINTER", "COLLECTION"}:
                    fixed = self.raw(prop, "fixed_type")
                    observed = self.raw(fixed, "identifier")
                    expected_fixed = checkpoint_proof.RUNTIME_FIXED.get((identifier, name))
                    facts.update(fixed_identifier=observed, expected_fixed_identifier=expected_fixed)
                    if observed != expected_fixed:
                        raise _checkpoint_descriptor_error(facts)
        # Runtime declarations such as Scene.cycles carry Python markers.
        # Screen their native metadata here; raw() still proves every field
        # actually read before dispatching its getter. Do not read markers.
        if identifier == "Object":
            keys = self.bounded(self.call(self.method(owner, "keys")), 128, "Object custom keys")
            if any(type(key) is not str for key in keys) or "active_selection_set" in keys:
                raise contract.refused("STORAGE_CHECKPOINT_STORED_UI_SELECTION_UNQUALIFIED")
        return properties

    def pointer_field(self, owner, name, fixed_type):
        prop = next((item for item in self.descriptors(owner) if self.raw(item, "identifier") == name), None)
        if (prop is None or self.raw(prop, "is_runtime") or not self.raw(prop, "is_readonly")
                or self.raw(prop, "type") != "POINTER" or self.raw(prop, "is_registered")
                or self.raw(self.raw(prop, "fixed_type"), "identifier") != fixed_type):
            raise contract.refused("STORAGE_CHECKPOINT_POINTER_DESCRIPTOR_CHANGED")
        return self.raw(owner, name)

    def value(self, raw, *, depth=0, budget=None):
        if budget is None:
            budget = [4096]
        budget[0] -= 1
        if depth > 8 or budget[0] < 0:
            raise contract.refused("STORAGE_CHECKPOINT_VALUE_BUDGET")
        kind = type(raw)
        if raw is None or kind in {bool, int}:
            return raw
        if kind is str:
            if len(raw) > 4096:
                raise contract.refused("STORAGE_CHECKPOINT_VALUE_BUDGET")
            return raw
        if kind is float:
            if not math.isfinite(raw):
                raise contract.refused("STORAGE_CHECKPOINT_NONFINITE_VALUE")
            return raw
        # Writable ParticleEdit/ParticleBrush fields are primitive scalars,
        # fixed arrays, enums, or native pointers. Other forms remain refused.
        if any(base is self.base for base in graph._class_mro(kind)):
            return ("RNA", *self.token(raw))
        if kind not in (tuple, list, set) and kind is not self.array_type:
            raise contract.refused("STORAGE_CHECKPOINT_VALUE_KIND_UNQUALIFIED")
        values = self.bounded(raw, 256, "fixed values")
        if kind is set:
            if any(type(item) is not str for item in values):
                raise contract.refused("STORAGE_CHECKPOINT_ENUM_SHAPE")
            values = sorted(values)
        return tuple(self.value(item, depth=depth + 1, budget=budget) for item in values)

    def method(self, owner, name):
        descriptor = graph._class_find(type(owner), name)
        if (type(descriptor) is not MethodDescriptorType or descriptor.__objclass__ is not self.base
                or name != "keys" or descriptor.__name__ != name):
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_METHOD_CHANGED")
        return descriptor.__get__(owner)

    def settings(self, owner):
        result = []
        for prop in self.descriptors(owner):
            if self.raw(prop, "is_runtime") or self.raw(prop, "is_readonly"):
                continue
            name, kind = self.raw(prop, "identifier"), self.raw(prop, "type")
            if kind not in checkpoint_proof.PRIMITIVES | {"POINTER"}:
                raise contract.refused("STORAGE_CHECKPOINT_WRITABLE_KIND_CHANGED")
            result.append((name, self.value(self.raw(owner, name))))
        # These settings owners have no admitted IDProperty payload. Refuse
        # populated keys instead of omitting unknown values from protection.
        keys = self.method(owner, "keys")
        supplied, error = self.call(_checkpoint_native_keys, keys)
        if error is not None:
            # Preserve the previous native-TypeError branch's third control
            # check. It is outside the native-only catch, like both call gates.
            origin, check = self._origin, self.check
            if self._origin is not origin or any(object.__getattribute__(self, name) is not value for name, value in origin):
                raise contract.refused("STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED")
            check()
            if self._origin is not origin or any(object.__getattribute__(self, name) is not value for name, value in origin):
                raise contract.refused("STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED")
            if type(error) is not TypeError:
                raise error
            arguments = error.args
            if (type(arguments) is not tuple or len(arguments) != 1 or type(arguments[0]) is not str
                    or arguments[0] != "bpy_struct.keys(): this type doesn't support IDProperties"):
                raise error
            return tuple(result), ()
        if self.bounded(supplied, 128, "custom keys"):
            raise contract.refused("STORAGE_CHECKPOINT_CUSTOM_SETTINGS_UNQUALIFIED")
        return tuple(result), ()

    def references(self, scene):
        database = self.call(getattr, self.bpy, "data")
        method = self.raw(database, "user_map")
        supplied = self.call(lambda: method(subset={scene}))
        if type(supplied) is not dict or len(supplied) != 1 or next(iter(supplied)) is not scene:
            raise contract.refused("STORAGE_CHECKPOINT_REVERSE_MAP_CHANGED")
        direct = self.bounded(next(iter(dict.values(supplied))), 128, "Scene consumers")
        rows = []
        for user in direct:
            rna = self.raw(user, "bl_rna")
            method = self.raw(user, "user_of_id")
            count = graph._int(self.call(method, scene), 65536)
            rows.append((self.token(user), graph._text(self.raw(rna, "identifier")), graph._text(self.raw(user, "name")), count))
        return ((self.token(scene), graph._int(self.raw(scene, "users"), 65536),
                 graph._bool(self.raw(scene, "use_fake_user")), tuple(sorted(rows))),)


class _StorageCheckpointPlan(checkpoint_roles.Plan):
    """Original canonical push authority with B2 checked native readers."""
    def __init__(self, bpy, scene, access, validator):
        self.access = access
        super().__init__(bpy, scene, active_validator=validator, include_brush=True)

    def _read(self):
        read, scene = self.access, self.scene
        settings = read.pointer_field(scene, "tool_settings", "ToolSettings")
        particle = read.pointer_field(settings, "particle_edit", "ParticleEdit")
        if any(read.raw(prop, "identifier") == "scene" for prop in read.descriptors(particle)):
            raise contract.refused("STORAGE_CHECKPOINT_EXPOSED_SCENE_ROLE")
        particle_object = read.pointer_field(particle, "object", "Object")
        original = read.pointer_field(scene, "original", "ID")
        context = read.call(getattr, self.bpy, "context")
        layer = read.raw(context, "view_layer")
        checkpoint_roles.mark_view_layer_sync_possible()
        active = read.active(layer)
        if active is not None:
            self.active_validator(self.bpy, active)
            if (read.bounded(read.raw(active, "particle_systems"), 1, "particle sources")
                    or read.pointer_field(active, "soft_body", "SoftBodySettings") is not None):
                raise contract.refused("STORAGE_CHECKPOINT_ACTIVE_CACHE_SOURCE")
        owners = (read.token(scene), read.key(settings), read.key(particle), read.token(original), read.token(active))
        count = graph._int(read.call(read.raw(scene, "user_of_id"), scene), 65536)
        return owners, count, read.token(particle_object)

    def references(self):
        self.check_after_read()
        records = self.access.references(self.scene)
        identity, users, fake_user, direct = records[0]
        own = tuple(record for record in direct if record[0] == identity)
        expected = () if self.expected[0] == 0 else ((identity, "Scene", self.access.raw(self.scene, "name"), 1),)
        if own != expected:
            raise contract.refused("STORAGE_CHECKPOINT_SCENE_SELF_CONSUMERS_CHANGED")
        return ((identity, users, fake_user, tuple(record for record in direct if record[0] != identity)),)

    def authored(self):
        self.check_after_read()
        read = self.access
        settings = read.pointer_field(self.scene, "tool_settings", "ToolSettings")
        particle = read.pointer_field(settings, "particle_edit", "ParticleEdit")
        brush = read.pointer_field(particle, "brush", "ParticleBrush")
        if brush is None or read.pointer_field(brush, "curve", "CurveMapping") is not None:
            raise contract.refused("STORAGE_CHECKPOINT_BRUSH_CURVE_UNQUALIFIED")
        return (self.owners, self.references(), read.settings(particle), read.key(brush), read.settings(brush), (None, None))


class CheckpointRoles:
    """Retained B2 owners and the sole native undo-poll role transition.

    This admits no previous foreign weak owner. Broader transfer preservation
    remains 1.0 work; clearing that owner would itself be an unowned edit.
    """
    __slots__ = (
        "access",
        "access_origin",
        "after_readback",
        "before_readback",
        "bound_digest",
        "bpy",
        "gate",
        "identities",
        "initial_roles",
        "last_readback",
        "memberships",
        "mesh",
        "native_push_completed",
        "obj",
        "origin",
        "owner_origin",
        "phase",
        "plan",
        "plan_fields",
        "scene",
        "validator",
    )

    def __init__(self, bpy, metadata, gate):
        self.bpy, self.gate, self.obj, self.mesh = bpy, gate, metadata.obj, metadata.mesh
        self.access = _CheckpointRoleAccess(bpy, gate.pure)
        self.scene = self.access.raw(self.access.call(getattr, bpy, "context"), "scene")
        self.validator = self._validate_active
        self.access_origin = tuple((name, getattr(self.access, name)) for name in _CheckpointRoleAccess.__slots__)
        self.owner_origin = (bpy, gate, self.obj, self.mesh, self.scene, self.validator, self.access, self.access_origin)
        # Explicit validator: the general Scene evaluation scope is not an
        # authority for this separate, source-qualified mesh profile.
        self.plan = _StorageCheckpointPlan(bpy, self.scene, self.access, self.validator)
        self.plan_fields = tuple((key, value) for key, value in vars(self.plan).items() if key != "expected")
        self.initial_roles = self.plan.expected
        self.phase, self.memberships, self.bound_digest, self.origin = 0, None, None, None
        self.before_readback = self.last_readback = self.after_readback = None
        self.native_push_completed = False
        self.identities = tuple(self.access.identity(owner, kind)
                                for owner, kind in ((self.scene, "Scene"), (self.obj, "Object"), (self.mesh, "Mesh")))
        CheckpointRoles.check_after_read(self)

    def _validate_active(self, bpy, active):
        if (bpy is not self.bpy or active is not self.obj or self.access.raw(active, "type") != "MESH"
                or self.access.raw(active, "data") is not self.mesh):
            raise contract.refused("STORAGE_CHECKPOINT_ACTIVE_OWNER_CHANGED")

    def check_identity(self, origin=None):
        """Pure held-instance proof, also safe during paused turn admission."""
        if (type(self) is not CheckpointRoles or type(self.plan) is not _StorageCheckpointPlan
                or (origin is not None and self.origin is not origin)
                or type(self.phase) is not int or self.phase not in (0, 1)):
            raise contract.refused("STORAGE_CHECKPOINT_ROLE_OWNER_CHANGED")
        if origin is not None and (type(origin) is not tuple or len(origin) != 8
                or origin[0] is not self or origin[1] is not self.plan
                or origin[2] is not self.plan_fields or origin[3] is not self.identities
                or origin[4] is not self.initial_roles or type(self.memberships) is not int
                or origin[5] != self.memberships
                or origin[6] is not self.bound_digest or origin[7] is not self.owner_origin):
            raise contract.refused("STORAGE_CHECKPOINT_ROLE_OWNER_CHANGED")
        if any(actual is not held for actual, held in zip(
                (self.bpy, self.gate, self.obj, self.mesh, self.scene, self.validator, self.access, self.access_origin), self.owner_origin, strict=True)):
            raise contract.refused("STORAGE_CHECKPOINT_ROLE_OWNER_CHANGED")
        if (type(self.access) is not _CheckpointRoleAccess
                or any(getattr(self.access, name) is not value for name, value in self.access_origin)):
            raise contract.refused("STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED")
        fields = vars(self.plan)
        if (len(fields) != len(self.plan_fields) + 1 or any(type(key) is not str for key in fields)
                or any(key not in fields or fields[key] is not value for key, value in self.plan_fields)
                or fields.get("active_validator") is not self.validator
                or fields.get("previous_witness") is not None):
            raise contract.refused("STORAGE_CHECKPOINT_ROLE_OWNER_CHANGED")
        expected = fields.get("expected")
        if self.phase == 0:
            valid_phase = expected is self.initial_roles
        else:
            # The canonical Plan creates exactly (1, held_active_token). Check
            # builtin shapes before comparisons; a replaced expected value must
            # never dispatch a provider-installed equality callback.
            valid_phase = (type(expected) is tuple and len(expected) == 2
                           and type(expected[0]) is int and expected[0] == 1
                           and expected[1] is self.plan.active)
        if not valid_phase:
            raise contract.refused("STORAGE_CHECKPOINT_ROLE_PHASE_CHANGED")

    def check_after_read(self):
        CheckpointRoles.check_identity(self, self.origin)
        self.gate.pure()
        read = self.access
        database = read.call(getattr, self.bpy, "data")
        for (owner, kind, family), identity in zip(((self.scene, "Scene", "scenes"),
                                                  (self.obj, "Object", "objects"),
                                                  (self.mesh, "Mesh", "meshes")), self.identities, strict=True):
            actual = read.identity(owner, kind)
            if actual != identity or read.lookup(read.raw(database, family), dict(actual)["name"]) is not owner:
                raise contract.refused("STORAGE_CHECKPOINT_MAIN_OWNER_CHANGED")
        owners, self_count, particle_object = _StorageCheckpointPlan._read(self.plan)
        native_self_count = graph._int(read.call(read.raw(self.scene, "user_of_id"), self.scene), 65536)
        if (native_self_count != self_count or owners != self.plan.owners
                or (self_count, particle_object) != self.plan.expected):
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_ROLES_CHANGED")
        self.gate.pure()
        return owners, self_count, particle_object

    def check_scene_object_count(self, reader, scene, obj, memberships):
        if (reader.bpy is not self.bpy or scene is not self.scene or obj is not self.obj
                or type(memberships) is not int or memberships < 1
                or (self.memberships is not None and memberships != self.memberships)):
            raise contract.refused("STORAGE_CHECKPOINT_STRUCTURAL_MEMBERSHIPS_CHANGED")
        before = CheckpointRoles.check_after_read(self)
        weak = int(before[1] == 1 and before[2] == self.plan.active)
        count = graph._int(self.access.call(self.access.raw(scene, "user_of_id"), obj), 65536)
        if count != memberships + weak:
            error = contract.refused("SCENE_OBJECT_REFERENCE_ROLES_CHANGED")
            error.context.update(expected_reference_count=memberships + weak, observed_reference_count=count)
            raise error
        after = CheckpointRoles.check_after_read(self)
        if before != after:
            raise contract.refused("STORAGE_CHECKPOINT_NATIVE_ROLES_CHANGED")
        if self.memberships is None:
            self.memberships = memberships  # Initial independently measured structural closure only.
        self.last_readback = {"owners": after[0], "scene_self_references": after[1],
                              "particle_object": after[2], "scene_object_references": count,
                              "structural_memberships": memberships, "weak_object_references": weak}
        if self.before_readback is None:
            self.before_readback = self.last_readback

    def authored(self):
        CheckpointRoles.check_after_read(self)
        if self.memberships is None:
            raise contract.refused("STORAGE_CHECKPOINT_STRUCTURAL_WITNESS_REQUIRED")
        # Plan.authored projects only its independently checked weak self role;
        # all writable particle/brush fields and ordinary references remain.
        return {"initial_owners": self.identities, "initial_roles": self.initial_roles,
                "structural_memberships": self.memberships,
                "authored": _StorageCheckpointPlan.authored(self.plan)}

    def bind_protected(self, facts):
        if self.origin is not None or self.last_readback is None or facts.get("checkpoint_roles") != CheckpointRoles.authored(self):
            raise contract.refused("STORAGE_CHECKPOINT_PROTECTED_WITNESS_REQUIRED")
        self.bound_digest = contract.digest(facts)
        self.origin = (self, self.plan, self.plan_fields, self.identities, self.initial_roles,
                       self.memberships, self.bound_digest, self.owner_origin)
        CheckpointRoles.check_identity(self, self.origin)

    def after_native_push(self, origin):
        CheckpointRoles.check_identity(self, origin)
        if origin is None:
            raise contract.refused("STORAGE_CHECKPOINT_PROTECTED_WITNESS_REQUIRED")
        # No getters/providers here. The held Plan claims its one-use canonical
        # delegate event before changing any expected phase.
        checkpoint_roles.Plan.after_native_push(self.plan)
        self.phase = 1
        self.native_push_completed = True

    def verified(self, digest):
        CheckpointRoles.check_identity(self, self.origin)
        if self.origin is None or digest != self.bound_digest:
            raise contract.refused("STORAGE_CHECKPOINT_PROTECTED_WITNESS_CHANGED")
        if self.native_push_completed:
            self.after_readback = self.last_readback

    def report(self):
        """Cached literals only, including when a caller has already stopped."""
        return {"profile": "B2_EXACT_CHECKPOINT_WEAK_ROLE_V1", "initial_roles": self.initial_roles,
                "before_readback": self.before_readback, "after_readback": self.after_readback,
                "native_push_completed": self.native_push_completed,
                "after_readback_measured": self.after_readback is not None,
                "protected_scope_sha256": self.bound_digest,
                "foreign_previous_owner_supported": False, "physical_cache_passivity_claimed": False}


def array_hash(bpy, plan, header, bindings, pure):
    pure()
    access = primitive._Access(bpy, pure)
    attribute = access.attribute(plan.metadata.mesh, header)
    values = access.field(attribute, header.native_class, "data")
    if type(values) is not bindings.collection_class:
        raise contract.refused("STORAGE_ARRAY_COLLECTION_CHANGED")
    output = primitive._buffers(header)[0]
    pure()
    bindings.verify()
    dict(bindings.descriptors)["foreach_get"](values, "vector" if header.data_type == "FLOAT2" else "value", output)
    pure()
    return contract.digest(primitive._bits(output, header))


def array_inventory(bpy, metadata, bindings, pure, excluded):
    """Read ARRAY payloads only, never an unselected SINGLE data getter."""
    result = {}
    for header in metadata.attributes:
        if header.storage != "ARRAY" or header.name in excluded:
            continue
        pure()
        access = primitive._Access(bpy, pure)
        attribute = access.attribute(metadata.mesh, header)
        data = access.field(attribute, header.native_class, "data")
        if type(data) is not bindings.collection_class:
            raise contract.refused("STORAGE_ARRAY_COLLECTION_CHANGED")
        channels = {"BOOLEAN": 1, "FLOAT2": 2, "FLOAT_VECTOR": 3, "INT": 1, "INT32_2D": 2}[header.data_type]
        field = "vector" if header.data_type in {"FLOAT2", "FLOAT_VECTOR"} else "value"
        if header.data_type == "BOOLEAN":
            output = memoryview(bytearray(header.count)).cast("?")
        else:
            output = array("f" if header.data_type in {"FLOAT2", "FLOAT_VECTOR"} else "i", [0]) * (header.count * channels)
        pure()
        bindings.verify()
        dict(bindings.descriptors)["foreach_get"](data, field, output)
        pure()
        result[header.name] = hashlib.sha256(memoryview(output).cast("B")).hexdigest()
    return result


def _material(reader, material):
    identity = reader.local_id(material, "Material")
    reader.no_animation(material, "Material")
    graph._runtime_absent(reader, material, "Material")
    graph._keys(reader, material, "Material", set())
    row = {"id": identity, "fields": graph._primitive_fields(reader, material, "Material")}
    if not material.use_nodes:
        row["tree"] = None
        return row
    tree = material.node_tree
    tree_identity = reader.local_id(tree, "ShaderNodeTree")
    reader.no_animation(tree, "ShaderNodeTree")
    graph._runtime_absent(reader, tree, "ShaderNodeTree")
    graph._keys(reader, tree, "ShaderNodeTree", set())
    nodes = graph._bounded(tree.nodes, 128)
    links = graph._bounded(tree.links, 256)
    retained, stream, rows = [tree, *nodes, *links], graph._Stream(), []
    for node in nodes:
        kind = graph._kind(reader, node, graph.NODES)
        reader.catalog(node, kind)
        if node.parent is not None:
            raise contract.refused("STORAGE_NESTED_NODE_PARENT_UNQUALIFIED")
        graph._keys(reader, node, kind, set())
        data = {"id": graph._node_identity(reader, node, tree, retained), "kind": kind,
                "fields": graph._primitive_fields(reader, node, kind)}
        for direction in ("inputs", "outputs"):
            data[direction] = [graph._socket(reader, stream, socket, node, tree, retained)
                               for socket in graph._bounded(getattr(node, direction), 64)]
        if kind == "ShaderNodeTexImage":
            data["image"] = None if node.image is None else reader.local_id(node.image, "Image")
            reader.catalog(node.image_user, "ImageUser")
            if node.image_user.use_auto_refresh:
                raise contract.refused("STORAGE_AUTO_IMAGE_REFRESH_UNQUALIFIED")
            data["image_user"] = graph._primitive_fields(reader, node.image_user, "ImageUser")
            data["mapping"] = graph._mapping(reader, stream, node, tree, retained)
        rows.append(data)
    row["tree"] = {"id": tree_identity,
                   "fields": graph._primitive_fields(reader, tree, "ShaderNodeTree"), "nodes": rows,
                   "links": [(graph._socket_identity(reader, link.from_socket, tree, retained),
                              graph._socket_identity(reader, link.to_socket, tree, retained),
                              graph._bool(link.is_valid), graph._bool(link.is_muted)) for link in links]}
    row["tree"]["embedded_native_identity_sha256"] = stream.native.hexdigest()
    return row


def protected_facts(bpy, metadata, gate, bindings, excluded, *, checkpoint_roles=None):
    """Complete admitted logical consumers; explicit refusal for broader roles.

    Native source qualification of these readbacks is a separate test gate.
    They may tag/unshare ARRAY/image caches and are not physical-passive reads.
    """
    pure = gate.pure
    pure()
    reader = graph._Reader(bpy, pure)
    obj, mesh = metadata.obj, metadata.mesh
    for owner, kind in ((obj, "Object"), (mesh, "Mesh")):
        reader.local_id(owner, kind)
        reader.no_animation(owner, kind)
        graph._runtime_absent(reader, owner, kind)
        graph._keys(reader, owner, kind, set())
    if (obj.parent is not None or len(obj.children) or len(obj.modifiers) or len(obj.constraints)
            or len(obj.vertex_groups) or obj.instance_type != "NONE"):
        raise contract.refused("STORAGE_HIERARCHY_RIG_MODIFIER_PROFILE_UNQUALIFIED")
    users = graph._user_map(reader, (obj, mesh))
    if users[mesh] != (obj,):
        raise contract.refused("STORAGE_SHARED_OR_UNKNOWN_MESH_CONSUMER")
    closure = graph._collection_closure(reader, obj, users[obj], checkpoint_roles=checkpoint_roles)
    materials = graph._bounded(mesh.materials, MAX_MATERIALS)
    if len(obj.material_slots) != len(materials):
        raise contract.refused("STORAGE_MATERIAL_SLOT_CHANGED")
    slots = []
    for index, slot in enumerate(obj.material_slots):
        reader.catalog(slot, "MaterialSlot")
        if slot.link != "DATA" or slot.material is not materials[index]:
            raise contract.refused("STORAGE_OBJECT_MATERIAL_OVERRIDE_UNQUALIFIED")
        slots.append(None if slot.material is None else reader.local_id(slot.material, "Material"))
    material_rows = [_material(reader, material) for material in materials if material is not None]
    images = graph._bounded(bpy.data.images, MAX_IMAGES)
    image_rows, total = [], 0
    for image in images:
        image_identity = reader.local_id(image, "Image")
        reader.no_animation(image, "Image")
        loaded = graph._bool(image.has_data)
        item = {"id": image_identity, "source": graph._text(image.source),
                "filepath": graph._text(image.filepath, 4096, blank=True), "loaded": loaded,
                "alpha": graph._text(image.alpha_mode), "colorspace": graph._text(image.colorspace_settings.name),
                "users": graph._int(image.users, 65536), "fake_user": graph._bool(image.use_fake_user)}
        if loaded:
            width, height = tuple(image.size)
            channels = graph._int(image.channels, 4, minimum=1)
            if (type(width) is not int or type(height) is not int or not 1 <= width <= 4096
                    or not 1 <= height <= 4096 or width * height > MAX_IMAGE_PIXELS):
                raise contract.refused("STORAGE_IMAGE_OBSERVER_BUDGET")
            total += width * height
            if total > MAX_AGGREGATE_PIXELS:
                raise contract.refused("STORAGE_AGGREGATE_IMAGE_OBSERVER_BUDGET")
            pure()
            gate.floor = max(gate.floor, BASE_MEMORY + width * height * channels * 12)
            pure()
            values = array("f", [0.]) * (width * height * channels)
            image.pixels.foreach_get(values)
            pure()
            item.update(size=(width, height), channels=channels, dirty=graph._bool(image.is_dirty),
                        pixels=hashlib.sha256(memoryview(values).cast("B")).hexdigest())
        packed = image.packed_file
        if packed is not None:
            reader.catalog(packed, "PackedFile")
            size = graph._int(packed.size, 640 * 1024**2, minimum=1)
            gate.floor = max(gate.floor, BASE_MEMORY + 2 * size)
            pure()
            data = packed.data
            if type(data) is not bytes or len(data) != size:
                raise contract.refused("STORAGE_PACKED_PAYLOAD_SHAPE")
            item["packed"] = hashlib.sha256(data).hexdigest()
        else:
            item["packed"] = None
        image_rows.append(item)
    face_ranges, next_loop = [], 0
    polygons = graph._bounded(mesh.polygons, 32_768)
    counts = dict(metadata.counts)
    if len(polygons) != counts["polygons"]:
        raise contract.refused("STORAGE_POLYGON_LAYOUT_CHANGED")
    for index, polygon in enumerate(polygons):
        reader.catalog(polygon, "MeshPolygon")
        ordinal = graph._int(polygon.index, 32767)
        start = graph._int(polygon.loop_start, 131072)
        total = graph._int(polygon.loop_total, 131072, minimum=3)
        if ordinal != index or start != next_loop or start + total > counts["loops"]:
            raise contract.refused("STORAGE_POLYGON_LAYOUT_CHANGED")
        face_ranges.append((ordinal, start, total))
        next_loop += total
    if next_loop != counts["loops"]:
        raise contract.refused("STORAGE_POLYGON_LAYOUT_CHANGED")
    mesh_fields = graph._primitive_fields(reader, mesh, "Mesh",
                                         exclude=frozenset({"texspace_location", "texspace_size"}))
    if graph._bool(mesh.use_auto_texspace) is False:
        from .uv_edit_guard import _manual_texspace_vector
        for name in ("texspace_location", "texspace_size"):
            pure()
            mesh_fields[name] = [graph._float(value) for value in _manual_texspace_vector(mesh, name)]
            pure()
    context = bpy.context
    fact = {"object_fields": graph._primitive_fields(reader, obj, "Object", exclude=frozenset({"dimensions",
                "matrix_world", "matrix_local", "matrix_basis", "matrix_parent_inverse"})),
            "parent_inverse": [graph._vector(line, 4) for line in graph._bounded(obj.matrix_parent_inverse, 4)],
            "mesh_fields": mesh_fields, "slots": slots,
            "array_payloads": array_inventory(bpy, metadata, bindings, pure, excluded), "polygon_loop_ranges": face_ranges,
            "material_rows": material_rows, "images": image_rows,
            "incoming": sorted([(owner.bl_rna.identifier, owner.name, owner.session_uid) for owner in closure]),
            "context": {"mode": context.mode, "scene": reader.local_id(context.scene, "Scene"),
                        "active": None if context.view_layer.objects.active is None else
                        reader.local_id(context.view_layer.objects.active, "Object"),
                        "selection": sorted((reader.local_id(value, "Object")
                                             for value in graph._bounded(context.selected_objects, 512)),
                                            key=lambda row: (row["name"], row["session_uid"], row["pointer"]))}}
    if checkpoint_roles is not None:
        fact["checkpoint_roles"] = CheckpointRoles.authored(checkpoint_roles)
    pure()
    return fact


def preview_fingerprint(context, parameters, plan, facts, source_seal):
    connection = None if context.request_lifecycle is None else context.request_lifecycle.connection
    return contract.digest({"policy": contract.POLICY, "request": parameters.plain(), "plan": plan.fingerprint,
                            "protected": facts, "registry": id(context.registry), "state": id(context.state),
                            "connection": id(connection), "source": source_seal.fingerprint(),
                            "plan_epoch": get_task_plans(context.state).evidence_epoch})
