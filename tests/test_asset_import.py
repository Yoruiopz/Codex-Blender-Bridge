from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.asset_import import AssetImportTools, load_definitions


@pytest.fixture
def module(addon_package):
    return importlib.import_module(addon_package + ".tools.asset_import")


def test_import_metadata_declares_private_cleanup_and_all_native_domains(module, addon_package):
    registry = importlib.import_module(addon_package + ".tool_registry").ToolRegistry()
    module.register_tools(registry)
    definitions = {tool.name: tool for tool in load_definitions()}
    preview, mutation = definitions["asset.import_preview"], definitions["asset.import"]
    assert not preview.modifying and mutation.modifying
    assert set(preview.required_permissions) == {"INSPECT_SCENE", "ACCESS_EXTERNAL_FILES"}
    assert set(mutation.required_permissions) == {
        "INSPECT_SCENE",
        "ACCESS_EXTERNAL_FILES",
        "EDIT_SCENE",
        "TRANSFORM_OBJECTS",
        "EDIT_MESH",
        "EDIT_MATERIALS",
        "EDIT_ANIMATION",
        "DELETE_OBJECTS",
    }
    assert "SAVE_PROJECT" not in mutation.required_permissions
    native = registry.get("asset.import")
    assert {permission.value for permission in native.permissions} == set(
        mutation.required_permissions
    )
    assert native.modifies


@pytest.mark.parametrize(
    "flag,code", [("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")]
)
def test_stop_after_lifecycle_callback_blocks_native_mutation_gate(module, flag, code):
    flags = {}
    context = NS(
        require=lambda *args: None,
        state=NS(snapshot=lambda: flags),
        check_cancelled=lambda: flags.update({flag: True}),
    )
    with pytest.raises(module.BridgeError) as caught:
        module._gate(context, writing=True)
    assert caught.value.code == code


def test_lifecycle_callback_cannot_revoke_permission_after_initial_gate(module):
    live = {"allowed": True}

    def require(*args):
        if not live["allowed"]:
            raise module.BridgeError("PERMISSION_DENIED", "revoked")

    context = NS(
        require=require,
        state=NS(snapshot=lambda: {}),
        check_cancelled=lambda: live.update(allowed=False),
    )
    with pytest.raises(module.BridgeError) as caught:
        module._gate(context, writing=True)
    assert caught.value.code == "PERMISSION_DENIED"


def test_source_animation_request_is_explicitly_unsupported_before_blender_or_io(
    module, monkeypatch
):
    context = NS(require=lambda *args: None, state=NS(snapshot=lambda: {}), check_cancelled=None)
    monkeypatch.setattr(module, "require_blender", lambda: pytest.fail("Blender inspected"))
    with pytest.raises(module.BridgeError) as caught:
        module.import_preview(
            context,
            {"filepath": "/unapproved/source.glb", "format": "GLB", "include_animation": True},
        )
    assert caught.value.code == "NOT_IMPLEMENTED"


def test_removed_rna_handles_never_replace_primary_retention_evidence(module):
    class Removed:
        def as_pointer(self):
            raise ReferenceError("StructRNA was removed")

    live = NS(as_pointer=lambda: 123, name="Retained Imported Mesh")
    assert module._retained_names({"meshes": {1: Removed(), 2: live}, "objects": {}}) == {
        "meshes": ["Retained Imported Mesh"]
    }


@pytest.mark.parametrize(
    "method,field,value",
    [
        ("asset_import", "expected_fingerprint", "guessed"),
        ("asset_import", "collection_name", ""),
        ("asset_import", "include_animation", 1),
        ("asset_import", "accepted_losses", ["SILENTLY_DROP_ANIMATION"]),
        ("asset_import_preview", "format", "glTF"),
    ],
)
def test_mcp_rejects_ambiguous_or_undeclared_contract_values(method, field, value):
    hints = get_type_hints(getattr(AssetImportTools, method), include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(hints[field]).validate_python(value)


def test_fbx_preview_loss_acknowledgements_can_be_forwarded_unchanged():
    hints = get_type_hints(AssetImportTools.asset_import, include_extras=True)
    losses = ["AXIS_UNIT_CONVERSION", "FBX_MESH_RECONSTRUCTION"]
    assert TypeAdapter(hints["accepted_losses"]).validate_python(losses) == losses


def test_mcp_forwards_exact_native_read_and_mutation_contract():
    calls = []

    async def call(name, params):
        calls.append((name, params))
        return {"forwarded": True}

    tools = AssetImportTools(NS(call=call))
    asyncio.run(
        tools.asset_import(
            "/approved/source.fbx",
            "FBX",
            "Imported Asset",
            "a" * 64,
            ["AXIS_UNIT_CONVERSION", "FBX_MESH_RECONSTRUCTION"],
        )
    )
    assert calls == [
        (
            "asset.import",
            {
                "filepath": "/approved/source.fbx",
                "format": "FBX",
                "collection_name": "Imported Asset",
                "expected_fingerprint": "a" * 64,
                "accepted_losses": ["AXIS_UNIT_CONVERSION", "FBX_MESH_RECONSTRUCTION"],
                "include_animation": False,
            },
        )
    ]


@pytest.fixture
def compensation(module, monkeypatch):
    """Native-finalizer boundary with independently observable deletion attempts."""
    live = {
        "permission": True,
        "paused": False,
        "consumer": False,
        "changed": False,
        "protected_edit": False,
        "context_changed": False,
        "collections": 0,
    }
    deletions, collected = [], []

    def require(*args):
        if not live["permission"]:
            raise module.BridgeError("PERMISSION_DENIED", "revoked during finalization")

    context = NS(
        require=require, check_cancelled=None, state=NS(snapshot=lambda: {"paused": live["paused"]})
    )
    before, protected = {"before": True}, {"protected": True}
    owned = {
        name: {} for name in ("objects", "meshes", "materials", "images", "collections", "scenes")
    }
    signature = {"owned": "exact"}
    scene = NS(collection=NS(children=[]))
    monkeypatch.setattr(module, "_new_ids", lambda *args: owned)
    monkeypatch.setattr(
        module,
        "_owned_signature",
        lambda *args: {"owned": "newer"} if live["changed"] else signature,
    )
    monkeypatch.setattr(
        module,
        "_guard",
        lambda *args: {"protected": False} if live["protected_edit"] else protected,
    )

    def closure(*args, **kwargs):
        if live["consumer"]:
            raise module.invalid_argument("A protected consumer acquired an owned image")

    monkeypatch.setattr(module, "_closure", closure)

    def admission(*args):
        if live["context_changed"]:
            raise module.invalid_argument("Context moved to another scene")

    monkeypatch.setattr(module, "_runtime_admission", admission)
    monkeypatch.setattr(
        module, "_remove_private_scene", lambda *args: deletions.append("private_scene")
    )
    callback = [lambda: None]

    def collect():
        collected.append(True)
        callback[0]()
        return 0

    monkeypatch.setattr(module, "gc", NS(collect=collect))
    return NS(
        module=module,
        live=live,
        context=context,
        before=before,
        protected=protected,
        owned=owned,
        signature=signature,
        scene=scene,
        deletions=deletions,
        collected=collected,
        callback=callback,
    )


def compensate(env, format="FBX"):
    intervals = {}
    result = env.module._cleanup(
        NS(),
        env.context,
        env.before,
        env.owned,
        env.signature,
        env.scene,
        None,
        None,
        published=False,
        protected=env.protected,
        native_format=format,
        blocking=intervals,
    )
    return result, intervals


def test_fbx_cycle_release_precedes_measured_revalidated_compensation(compensation):
    result, intervals = compensate(compensation)
    assert result == "removed" and compensation.deletions == ["private_scene"]
    assert compensation.collected == [True] and intervals["fbx_cycle_release_seconds"] >= 0.0


@pytest.mark.parametrize(
    "change", ["permission", "paused", "consumer", "changed", "protected_edit", "context_changed"]
)
def test_finalizer_revocation_new_consumer_or_newer_edit_prevents_all_compensation_writes(
    compensation, change
):
    env = compensation
    env.callback[0] = lambda: env.live.update({change: change != "permission"})
    result, intervals = compensate(env)
    assert result.startswith("retained_") and env.deletions == []
    assert env.collected == [True] and intervals["fbx_cycle_release_seconds"] >= 0.0


def test_glb_compensation_does_not_run_global_collection(compensation):
    result, intervals = compensate(compensation, "GLB")
    assert result == "removed" and compensation.collected == [] and intervals == {}


class NativeID:
    def __init__(self, **fields):
        self.__dict__.update(fields)


@pytest.mark.parametrize(
    "change", ["real_user", "fake_user", "mapped_consumer", "window_owner", "context", "contents"]
)
def test_private_scene_removal_requires_no_external_or_ui_owner(module, change):
    removed = []
    stage = NativeID(
        users=1, use_extra_user=True, use_fake_user=False, objects=[], collection=NS(children=[])
    )
    current = NativeID()
    windows, mapped = [], {}
    if change == "real_user":
        stage.users = 2
    elif change == "fake_user":
        stage.use_fake_user = True
    elif change == "mapped_consumer":
        mapped[stage] = [NativeID()]
    elif change == "window_owner":
        windows = [NS(scene=stage)]
    elif change == "context":
        current = stage
    else:
        stage.objects = [NativeID()]
    bpy = NS(
        context=NS(scene=current),
        data=NS(
            user_map=lambda **kwargs: mapped,
            window_managers=[NS(windows=windows)],
            scenes=NS(remove=lambda *args, **kwargs: removed.append(True)),
        ),
    )
    with pytest.raises(module.BridgeError, match="removal is refused"):
        module._remove_private_scene(bpy, stage)
    assert removed == []


def test_empty_private_scene_internal_extra_user_is_not_an_external_edge(module):
    removed = []
    stage = NativeID(
        users=1, use_extra_user=True, use_fake_user=False, objects=[], collection=NS(children=[])
    )
    bpy = NS(
        context=NS(scene=NativeID()),
        data=NS(
            user_map=lambda **kwargs: {},
            window_managers=[],
            scenes=NS(remove=lambda *args, **kwargs: removed.append((args, kwargs))),
        ),
    )
    module._remove_private_scene(bpy, stage)
    assert removed == [((stage,), {"do_unlink": True})]


def test_preview_from_previous_process_nonce_is_rejected_before_staging(module, monkeypatch):
    context = NS(require=lambda *args: None, state=NS(snapshot=lambda: {}), check_cancelled=None)
    source = NS(payload=b"complete admitted source", proof=lambda: {"file_sha256": "b" * 64})
    monkeypatch.setattr(module, "require_blender", lambda: NS())
    monkeypatch.setattr(module, "_runtime_admission", lambda *args: None)
    monkeypatch.setattr(module, "_inventory", lambda *args: {})
    monkeypatch.setattr(module, "_guard", lambda *args: {"same_destination": True})
    monkeypatch.setattr(module, "_source_root", lambda: "/approved")
    monkeypatch.setattr(module, "read_source", lambda *args: source)
    monkeypatch.setattr(
        module, "preflight_glb", lambda *args: {"required_accepted_losses": ["VERTEX_SPLITS"]}
    )
    params = {"filepath": "/approved/asset.glb", "format": "GLB"}
    monkeypatch.setattr(module, "SESSION_NONCE", "old-process-nonce")
    old = module.import_preview(context, params)
    monkeypatch.setattr(module, "SESSION_NONCE", "new-process-nonce")
    assert module.import_preview(context, params)["fingerprint"] != old["fingerprint"]
    monkeypatch.setattr(
        module,
        "OwnedInput",
        lambda *args: pytest.fail("staging allocated for an old process preview"),
    )
    with pytest.raises(module.BridgeError, match="current source/destination preview fingerprint"):
        module.import_asset(
            context,
            {
                **params,
                "collection_name": "Unused",
                "expected_fingerprint": old["fingerprint"],
                "accepted_losses": old["required_accepted_losses"],
            },
        )


def identity_id(uid, *, override=None):
    return NativeID(
        session_uid=uid,
        name="Same Name",
        as_pointer=lambda: 123,
        library=None,
        override_library=override,
        is_editable=True,
        use_fake_user=False,
        use_extra_user=False,
        users=0,
    )


def test_native_uid_replacement_at_same_name_and_pointer_is_new_and_never_adopted(module):
    old, replacement = identity_id(11), identity_id(12)
    data = NS(actions=[], objects=[], materials=[], images=[], meshes=[old])
    bpy = NS(data=data)
    before = module._inventory(bpy)
    assert before["meshes"] == {11: old}
    assert module._key(old) == module._key(replacement)
    assert old.name == replacement.name and module._id_state(old) != module._id_state(replacement)
    data.meshes = [replacement]
    assert module._new_ids(bpy, before)["meshes"] == {12: replacement}
    with pytest.raises(module.BridgeError, match="removed or replaced"):
        module._guard(bpy, before)
    with pytest.raises(module.BridgeError, match="removed or replaced"):
        module._closure(bpy, {"meshes": {11: old}}, None, None, None)


def test_override_rna_without_id_uid_does_not_break_id_identity_evidence(module):
    override = NativeID(as_pointer=lambda: 456)
    state = module._id_state(identity_id(11, override=override))
    assert 11 in state and 456 in state


@pytest.mark.parametrize("uid", [None, 0, -1, True, "123"])
def test_native_identity_never_falls_back_to_reusable_pointer(module, uid):
    with pytest.raises(module.BridgeError, match="native ID session_uid"):
        module._uid(NativeID(session_uid=uid, as_pointer=lambda: 123))


@pytest.mark.parametrize(
    "flag,code", [("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")]
)
def test_permission_provider_stop_state_is_checked_after_it_returns_grant(module, flag, code):
    flags, order = {}, []

    def require(*args):
        order.append("permission_provider")
        flags[flag] = True

    def cancelled():
        order.append("cancellation")

    def snapshot():
        order.append("terminal_flags")
        return flags

    context = NS(require=require, check_cancelled=cancelled, state=NS(snapshot=snapshot))
    with pytest.raises(module.BridgeError) as caught:
        module._gate(context, writing=True)
    assert caught.value.code == code
    assert order == ["cancellation", "permission_provider", "cancellation", "terminal_flags"]


@pytest.fixture
def write_boundary(module, monkeypatch):
    import copy

    live = {
        "context": (101, 202, "OBJECT", (303,), 303),
        "scene_uid": 1,
        "consumer": False,
        "owned": "exact",
        "paused": False,
    }
    protected = {"context": live["context"], "native_scene_uid": live["scene_uid"]}
    mutations = []

    class Links:
        def __contains__(self, key):
            return False

        def link(self, obj):
            mutations.append("link_owned_object")

        def unlink(self, obj):
            mutations.append("unlink_owned_object")

    stage_owner = NS(objects=Links())
    obj = NS(name="Imported", users_collection=[stage_owner])
    collection, stage = NS(as_pointer=lambda: 404, objects=Links()), NS(objects={"Imported": obj})
    owned, signature = {"objects": {4: obj}}, {"owned": "exact"}
    monkeypatch.setattr(
        module,
        "_guard",
        lambda *args, **kwargs: copy.deepcopy(
            {"context": live["context"], "native_scene_uid": live["scene_uid"]}
        ),
    )
    monkeypatch.setattr(module, "_owned_signature", lambda *args: {"owned": live["owned"]})

    def closure(*args, **kwargs):
        if live["consumer"]:
            raise module.invalid_argument("A new protected consumer acquired the imported ID")

    monkeypatch.setattr(module, "_closure", closure)
    monkeypatch.setattr(
        module, "_restore_selection", lambda *args: mutations.append("restore_selection")
    )
    callback = [lambda: None]
    context = NS(
        require=lambda *args: callback[0](),
        check_cancelled=None,
        state=NS(snapshot=lambda: {"paused": live["paused"]}),
    )
    return NS(
        module=module,
        live=live,
        protected=protected,
        mutations=mutations,
        collection=collection,
        stage=stage,
        owned=owned,
        signature=signature,
        context=context,
        callback=callback,
    )


def change_scope(env, change):
    context = list(env.live["context"])
    if change == "scene":
        context[0] += 1
    elif change == "view_layer":
        context[1] += 1
    elif change == "mode":
        context[2] = "EDIT_MESH"
    elif change == "project":
        env.live["scene_uid"] += 1
    elif change == "consumer":
        env.live["consumer"] = True
    elif change == "owned":
        env.live["owned"] = "newer"
    env.live["context"] = tuple(context)


@pytest.mark.parametrize("change", ["scene", "view_layer", "mode", "project", "consumer", "owned"])
def test_callback_scope_changes_block_owned_rehoming_before_any_link_or_unlink(
    write_boundary, change
):
    env = write_boundary
    env.callback[0] = lambda: change_scope(env, change)
    env.module._gate(env.context, writing=True)
    with pytest.raises(env.module.BridgeError):
        env.module._rehome_owned(
            NS(), {}, env.protected, env.owned, env.signature, env.stage, env.collection, None
        )
    assert env.mutations == []


@pytest.mark.parametrize("change", ["scene", "view_layer", "mode", "project", "consumer", "owned"])
def test_post_update_provider_scope_changes_block_selection_restoration(write_boundary, change):
    env = write_boundary
    env.callback[0] = lambda: change_scope(env, change)
    with pytest.raises(env.module.BridgeError):
        env.module._restore_import_selection(
            NS(),
            env.context,
            {},
            env.protected,
            env.owned,
            env.signature,
            env.stage,
            env.collection,
            None,
            [],
            None,
            None,
        )
    assert env.mutations == []


def test_expected_temporary_selection_difference_is_restored_after_full_scope_proof(write_boundary):
    env = write_boundary
    env.live["context"] = (101, 202, "OBJECT", (303, 404), 404)
    env.module._restore_import_selection(
        NS(),
        env.context,
        {},
        env.protected,
        env.owned,
        env.signature,
        env.stage,
        env.collection,
        None,
        [],
        None,
        None,
    )
    assert env.mutations == ["restore_selection"]


def test_cleanup_permission_provider_cannot_pause_then_return_a_grant(compensation):
    env = compensation
    env.context.require = lambda *args: env.live.update(paused=True)
    result, intervals = compensate(env)
    assert result.startswith("retained_") and env.deletions == []
    assert env.collected == [] and intervals == {}
