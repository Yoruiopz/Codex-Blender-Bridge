"""Private source, ownership and measured-preservation boundary for B2.

Logical readback can tag/unshare existing native storage. This module does not
claim physical cache passivity, a Python sandbox, or a reversible materializer.
"""
from __future__ import annotations

import hashlib
import importlib
from array import array
from types import (
    CodeType,
    FunctionType,
    GetSetDescriptorType,
    MappingProxyType,
    MethodType,
    ModuleType,
)

from . import current_pixels_graph as graph
from . import mesh_storage_contract as contract
from . import mesh_storage_prepare as primitive
from .native_save_profile import available_memory_facts
from .scene_job_reservations import TURN_METHOD
from .task_plans import get_task_plans
from .tool_registry import ToolContext, check_final_mutation

BASE_MEMORY = 64 * 1024**2
MAX_IMAGES = 8
MAX_IMAGE_PIXELS = 16_777_216
MAX_AGGREGATE_PIXELS = 33_554_432
MAX_MATERIALS = 32


class SourceSeal(tuple):
    """Held immutable source facts; verify never calls an unverified helper."""
    __slots__ = ()

    @classmethod
    def capture(cls):
        names = ("mesh_storage_source", "mesh_storage_contract", "mesh_storage_effects", "tools._mesh_storage_job",
                 "tools.mesh_storage", "native_save_profile", "state", "permissions", "task_plans", "tool_registry",
                 "request_lifecycle", "scene_jobs", "scene_job_authority", "executor", "command_queue",
                 "checkpoints", "checkpoint_completion", "current_pixels_graph", "mesh_storage_prepare", "uv_edit_guard")
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
        failure = contract.refused("STORAGE_SOURCE_CHANGED")
        native = (type, len, dict, str, FunctionType, ModuleType.__getattribute__,
                  type.__dict__["__dict__"].__get__, type.__dict__["__mro__"].__get__, failure)
        native += (ModuleType, event_kind)
        watches = []
        for module, name in ((graph, "BUILDS"), (graph, "_REGISTERED_TARGETS"),
                             (primitive, "COLLECTION_BINDING_PINS"), (primitive, "_VALUE_CLASSES")):
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
                                  tuple(watches), MappingProxyType(codes), verify_fact))

    def verify(self):
        raw_get = ().__class__.__getitem__
        rows, classes, functions, tables, native = raw_get(self, 0), raw_get(self, 1), raw_get(self, 2), raw_get(self, 3), raw_get(self, 4)
        kind, length, dict_type, str_type, fn_type, module_dict, class_dict, class_mro, failure, module_type = native[:10]
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
        from .tool_registry import CheckpointAdmissionBinding
        if type(binding) is not CheckpointAdmissionBinding:
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        binding_rows = tuple((name, getattr(binding, name)) for name in _BINDING_FIELDS)
        binding_callbacks = tuple((name, _callback_fact(getattr(binding, name), seal, internal=True))
                                  for name in ("readonly_callback", "native_push_callback", "marker_write_callback"))
    from .request_lifecycle import RequestLifetime
    lifetime, lifetime_rows, connection_rows, event_rows = fields.get("request_lifecycle"), (), (), []
    if lifetime is not None:
        if type(lifetime) is not RequestLifetime:
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        lifetime_rows = tuple((name, getattr(lifetime, name)) for name in ("connection", "deadline", "delivered", "rejected"))
        connection = lifetime.connection
        events = [lifetime.delivered, lifetime.rejected]
        if connection is not None:
            from .request_lifecycle import ConnectionLifetime
            if type(connection) is not ConnectionLifetime:
                raise contract.refused("STORAGE_CONTEXT_CHANGED")
            connection_rows = tuple((name, getattr(connection, name)) for name in ("disconnected", "background_active"))
            events += [connection.disconnected, connection.background_active]
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
    (original, seal, rows, callbacks, binding, binding_rows, binding_callbacks, lifetime, lifetime_rows,
     connection_rows, events, permissions) = proof
    verify_seal(seal)
    if context is not original or type(context) is not ToolContext:
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    fields = {name: ToolContext.__dict__[name].__get__(context, ToolContext) for name in _CONTEXT_FIELDS}
    if any(fields.get(name) is not value for name, value in rows):
        raise contract.refused("STORAGE_CONTEXT_CHANGED")
    for name, fact in callbacks:
        _check_callback(fields.get(name), fact)
    if binding is not None:
        if any(getattr(binding, name) is not value for name, value in binding_rows):
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        for name, fact in binding_callbacks:
            _check_callback(getattr(binding, name), fact)
    if lifetime is not None:
        if any(getattr(lifetime, name) is not value for name, value in lifetime_rows):
            raise contract.refused("STORAGE_CONTEXT_CHANGED")
        connection = lifetime.connection
        if any(getattr(connection, name) is not value for name, value in connection_rows):
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
        return tuple.__new__(cls, (cell, source_seal, facts(verify), facts(pure)))

    @property
    def context(self):
        return tuple.__getitem__(self, 0)["context"]

    @context.setter
    def context(self, context):
        seal = tuple.__getitem__(self, 1)
        verify_seal(seal)
        from .scene_jobs import _StartAdmission, _TurnAdmission
        binding = context.checkpoint_admission
        callback = None if binding is None else binding.callback
        if type(callback) is _StartAdmission or type(callback) is _TurnAdmission:
            proof = callback.storage_context_proof
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


def protected_facts(bpy, metadata, gate, bindings, excluded):
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
    closure = graph._collection_closure(reader, obj, users[obj])
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
    pure()
    return fact


def preview_fingerprint(context, parameters, plan, facts, source_seal):
    connection = None if context.request_lifecycle is None else context.request_lifecycle.connection
    return contract.digest({"policy": contract.POLICY, "request": parameters.plain(), "plan": plan.fingerprint,
                            "protected": facts, "registry": id(context.registry), "state": id(context.state),
                            "connection": id(connection), "source": source_seal.fingerprint(),
                            "plan_epoch": get_task_plans(context.state).evidence_epoch})
