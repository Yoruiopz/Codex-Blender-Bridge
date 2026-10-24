"""Source-specific external WM roles never qualify or discard Scene self roles."""

from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


class Properties(dict):
    def __iter__(self):
        return iter(self.values())


class RNA(NS):
    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other


class Native:
    def __init__(self, rna, **values):
        self.bl_rna, self.values, self.raw, self.hazards = rna, values, {}, {}
        self.count_reads = []

    def __getattr__(self, name):
        if name in self.hazards:
            self.hazards[name].append(name)
            raise AssertionError("Unreviewed getter resolved: " + name)
        if name in self.values:
            return self.values[name]
        raise AttributeError(name)

    def keys(self):
        return self.raw.keys()

    def __getitem__(self, name):
        return self.raw[name]

    def as_pointer(self):
        return id(self)

    def user_of_id(self, owner):
        self.count_reads.append(owner.as_pointer())
        return self.values["counts"].get(owner.as_pointer(), 0)


class ID(Native):
    pass


@pytest.fixture
def role_case(addon_package):
    module = importlib.import_module(f"{addon_package}.tools._rigid_scene_consumers")
    errors = importlib.import_module(f"{addon_package}.errors")
    types = NS(ID=ID)

    def prop(name, kind, *, runtime=False, readonly=False):
        return NS(identifier=name, type=kind, is_runtime=runtime, is_readonly=readonly)

    def owner(kind, fields, *, is_id=False, **values):
        if is_id:
            fields = {**fields, "name": "STRING", "session_uid": "INT", "library": "POINTER",
                      "override_library": "POINTER", "is_editable": "BOOLEAN"}
            values = {"name": kind, "session_uid": 12, "library": None, "override_library": None,
                      "is_editable": True, **values}
        rna = RNA(identifier=kind, properties=Properties({key: prop(key, value) for key, value in fields.items()}))
        setattr(types, kind, NS(bl_rna=rna))
        return (ID if is_id else Native)(rna, **values)

    layer = object()
    scene = owner("Scene", {"users": "INT", "use_fake_user": "BOOLEAN"}, is_id=True,
                  users=1, use_fake_user=False, counts={})
    workspace = owner("WorkSpace", {"use_pin_scene": "BOOLEAN", "sequencer_scene": "POINTER"},
                      is_id=True, use_pin_scene=False, sequencer_scene=None)
    window = owner("Window", {"scene": "POINTER", "workspace": "POINTER", "view_layer": "POINTER"},
                   scene=scene, workspace=workspace, view_layer=layer)
    wm = owner("WindowManager", {"windows": "COLLECTION"}, is_id=True,
               windows=[window], counts={scene.as_pointer(): 2})
    context = owner("Context", {key: "POINTER" for key in ("scene", "window_manager", "window", "workspace", "view_layer")},
                    scene=scene, window_manager=wm, window=window, workspace=workspace, view_layer=layer)
    data = owner("BlendData", {"scenes": "COLLECTION"}, scenes=[scene])
    incoming = [wm]
    data.values["user_map"] = lambda **kwargs: {scene: incoming}
    bpy = NS(types=types, context=context, data=data,
             app=NS(build_hash=b"62c1db4208e8", version=(4, 5, 14)))
    return NS(module=module, errors=errors, bpy=bpy, scene=scene, wm=wm, window=window,
              workspace=workspace, context=context, data=data, incoming=incoming, prop=prop)


def captured(case):
    return dict(case.module.external_scene_roles(case.bpy, case.scene))


def rejected(case):
    with pytest.raises(case.errors.BridgeError) as caught:
        captured(case)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context.get("scene_consumer_scope_complete", False) is False


@pytest.mark.parametrize(("build", "version"), [(b"62c1db4208e8", (4, 5, 14)), (b"d13f752e3b9c", (5, 2, 2))])
def test_exact_build_roles_preserve_raw_counts_without_qualifying_self(role_case, build, version):
    case = role_case
    case.bpy.app.build_hash, case.bpy.app.version = build, version
    case.incoming.append(case.scene)
    case.scene.values["counts"][case.scene.as_pointer()] = 3
    state = captured(case)
    assert state["raw_wm_scene_reference_count"] == 2
    assert state["native_roles"] == (("win.scene", "IDWALK_CB_USER_ONE"), ("win.unpinned_scene", "IDWALK_CB_NOP"))
    assert state["raw_scene_self_reference_count"] == 3
    assert state["scene_self_scope_qualified"] is False
    assert state["scope"] == "EXTERNAL_WINDOW_MANAGER_ONLY"


def test_one_reference_retains_distinct_source_role(role_case):
    case = role_case
    case.wm.values["counts"][case.scene.as_pointer()] = 1
    state = captured(case)
    assert state["native_roles"] == (("win.scene", "IDWALK_CB_USER_ONE"),)
    assert state["raw_wm_scene_reference_count"] == 1


@pytest.mark.parametrize("count", [0, 3, 4])
def test_unexplained_native_counts_refuse(role_case, count):
    case = role_case
    case.wm.values["counts"][case.scene.as_pointer()] = count
    rejected(case)


@pytest.mark.parametrize("change", ["unknown_build", "patch_mismatch", "extra_scene", "extra_window", "pin", "sequencer", "extra_consumer", "users"])
def test_extra_or_unproven_roles_refuse(role_case, change):
    case = role_case
    if change == "unknown_build":
        case.bpy.app.build_hash = b"unknown"
    elif change == "patch_mismatch":
        case.bpy.app.version = (4, 5, 13)
    elif change == "extra_scene":
        case.data.values["scenes"].append(object())
    elif change == "extra_window":
        case.wm.values["windows"].append(object())
    elif change == "pin":
        case.workspace.values["use_pin_scene"] = True
    elif change == "sequencer":
        case.workspace.values["sequencer_scene"] = case.scene
    elif change == "extra_consumer":
        case.incoming.append(case.workspace)
    else:
        case.scene.values["users"] = 2
    rejected(case)


@pytest.mark.parametrize("which", ["wm", "window", "workspace"])
def test_raw_ui_id_aliases_refuse_even_with_forged_expected_counts(role_case, which):
    case = role_case
    getattr(case, which).raw["alias"] = [1, case.scene]
    rejected(case)


def test_late_readonly_runtime_role_descriptor_refuses_without_getter(role_case):
    case = role_case
    reads = []
    case.workspace.bl_rna.properties["sequencer_scene"] = case.prop("sequencer_scene", "POINTER", runtime=True, readonly=True)
    case.workspace.hazards["sequencer_scene"] = reads
    rejected(case)
    assert reads == []


def test_unrelated_ui_runtime_property_is_never_resolved_by_explicit_role_reader(role_case):
    case = role_case
    reads = []
    case.wm.bl_rna.properties["preset_name"] = case.prop("preset_name", "STRING", runtime=True)
    case.wm.hazards["preset_name"] = reads
    assert captured(case)["raw_wm_scene_reference_count"] == 2
    assert reads == []


def test_wrong_window_context_refuses_without_counter_query(role_case):
    case = role_case
    case.window.values["scene"] = object()
    rejected(case)
    assert case.wm.count_reads == []


def test_raw_property_budget_is_aggregate_across_ui_owners(role_case):
    case = role_case
    case.wm.raw["notes"] = "x" * 5000
    case.workspace.raw["notes"] = "y" * 5000
    rejected(case)


@pytest.mark.parametrize("before_value,after_value", [(False, 0), (0, 0.0), (0.0, -0.0),
                                                     (True, 1), (1, 1.0)])
@pytest.mark.parametrize("nested", [False, True])
def test_raw_ui_custom_scalar_types_and_float_sign_are_distinct(role_case, before_value, after_value, nested):
    case = role_case
    def payload(value):
        return [value] if nested else value
    case.wm.raw["typed"] = payload(before_value)
    before = captured(case)["raw_ui_properties"]
    case.wm.raw["typed"] = payload(after_value)
    assert captured(case)["raw_ui_properties"] != before
    case.wm.raw["typed"] = payload(before_value)
    assert captured(case)["raw_ui_properties"] == before
