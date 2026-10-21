"""Bounded NLA clip, native transition and identity-preserving track lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..utils import int_param, reject_unknown_params, require_blender
from ._animation_scope import (
    Guard,
    action_content,
    action_token,
    action_users,
    affected_scope,
    bounded,
    digest,
    key,
    object_scope,
    rna_state,
    validate_slot,
)
from ._nla_controls import controls, new_clip, new_transition
from ._rna import bounded_name

MAX_TRACKS, MAX_STRIPS = 16, 64
COMMON = {"object_name", "affected_objects"}


def _name(raw: Any, field: str) -> str:
    result = bounded_name(raw, field, maximum=63)
    if len(result.encode("utf-8")) > 63 or any(ord(char) < 32 for char in result):
        raise invalid_argument(f"{field} must fit 63 UTF-8 bytes without control characters.")
    return result


def _exact(items: Any, name: str, label: str) -> Any:
    matches = [item for item in items if item.name == name]
    if len(matches) != 1:
        raise invalid_argument(f"An exact unique {label} is required.", name=name)
    return matches[0]


def _object(bpy: Any, params: Mapping[str, Any]) -> Any:
    obj = _exact(bounded(bpy.context.scene.objects, 256, "scene objects"), _name(params.get("object_name"), "object_name"), "object")
    object_scope(bpy, obj)
    data = obj.animation_data
    if bpy.context.mode != "OBJECT" or data is None or data.use_tweak_mode or not data.use_nla:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "NLA lifecycle requires Object Mode, enabled NLA and no tweak mode.")
    tracks = bounded(data.nla_tracks, MAX_TRACKS, "NLA tracks")
    if sum(len(track.strips) for track in tracks) > MAX_STRIPS:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Reviewed NLA scope exceeds 64 total strips.")
    return obj


def _track(obj: Any, raw: Any) -> Any:
    track = _exact(bounded(obj.animation_data.nla_tracks, MAX_TRACKS, "NLA tracks"), _name(raw, "track_name"), "NLA track")
    if track.lock:
        raise invalid_argument("Unlock the exact NLA track before lifecycle editing.")
    return track


def _strip(track: Any, raw: Any) -> Any:
    return _exact(bounded(track.strips, MAX_STRIPS, "NLA strips"), _name(raw, "strip_name"), "NLA strip")


def _quiet_authority(context: Any, method: str) -> None:
    # Permission providers can execute Blender callbacks; inspect stop flags after
    # the provider and freeze native state after every such callback before writes.
    context.require(Permission.EDIT_ANIMATION)
    flags = context.state.snapshot()
    if flags.get("emergency_stopped") or flags.get("paused"):
        raise BridgeError(ErrorCode.EMERGENCY_STOPPED if flags.get("emergency_stopped") else ErrorCode.AGENT_PAUSED,
                          "NLA lifecycle stopped before its next write.")
    registry = getattr(context, "registry", None)
    if registry is not None and registry.get(method).toolset not in registry.enabled_toolsets:
        raise BridgeError(ErrorCode.TOOLSET_DISABLED, "NLA toolset was disabled during live permission validation.")


class _Proof:
    """Exact stage state; only explicitly measured native changes may advance it."""

    def __init__(self, context: Any, obj: Any, method: str, affected: Any, extra_actions=()):
        self.bpy, self.context, self.obj = require_blender(), context, obj
        self.guard = Guard(self.bpy, context, method)
        self.guard.remember(obj, self.bpy.data.objects)
        self.affected = affected
        self.extra_actions = tuple(extra_actions)
        self.owners = tuple({key(owner): owner for owner in (obj, *bounded(self.bpy.context.selected_objects, 32, "selected objects"))}.values())
        self.extra: dict[tuple, Callable] = {}
        self.started = False
        self.expected = self.snapshot()
        self.original = deepcopy(self.expected)

    def snapshot(self) -> dict:
        bpy, result, actions = self.bpy, {}, {key(action): action for action in self.extra_actions}
        result[("context", "session")] = (key(bpy.context.scene), key(bpy.context.view_layer), bpy.data.filepath, bpy.context.mode)
        result[("context", "frame")] = (int(bpy.context.scene.frame_current), float(bpy.context.scene.frame_subframe))
        visible = bounded(bpy.context.view_layer.objects, 256, "view-layer objects")
        result[("context", "objects")] = tuple(key(obj) for obj in visible)
        for obj in visible:
            result[("selection", key(obj))] = bool(obj.select_get())
        result[("context", "active")] = key(bpy.context.view_layer.objects.active)
        result[("affected",)] = affected_scope(bpy, self.obj, self.affected)
        for owner in self.owners:
            oid, data = key(owner), owner.animation_data
            result[("owner", oid, "identity")] = (action_token(owner), owner.name, action_token(owner.data), key(data))
            if data is None:
                continue
            if data.use_tweak_mode or len(data.drivers):
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Reviewed NLA scope excludes tweak mode and drivers on scoped editor owners.")
            result[("owner", oid, "settings")] = rna_state(data)
            result[("owner", oid, "slot")] = key(getattr(data, "action_slot", None))
            tracks = bounded(data.nla_tracks, MAX_TRACKS, "NLA tracks")
            if sum(len(track.strips) for track in tracks) > MAX_STRIPS:
                raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Reviewed NLA owner exceeds 64 strips.")
            result[("owner", oid, "order")] = tuple(key(track) for track in tracks)
            result[("owner", oid, "active_track")] = key(data.nla_tracks.active)
            if data.action is not None:
                if owner == self.obj:
                    validate_slot(owner, data.action, getattr(data, "action_slot", None))
                actions[key(data.action)] = data.action
            for track in tracks:
                tid = key(track)
                for field, setting in rna_state(track):
                    result[("track", tid, field)] = setting
                result[("track", tid, "strips")] = tuple(key(strip) for strip in track.strips)
                for strip in track.strips:
                    sid = key(strip)
                    if strip.type not in {"CLIP", "TRANSITION"} or len(strip.modifiers) or len(strip.strips):
                        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "NLA lifecycle supports CLIP/TRANSITION strips without nested strips or strip modifiers.")
                    for field, setting in rna_state(strip):
                        result[("strip", sid, field)] = setting
                    result[("strip", sid, "native_type")] = strip.type
                    result[("strip", sid, "controls")] = controls(strip)
                    result[("strip", sid, "active")] = bool(strip.active)
                    result[("strip", sid, "slot_identity")] = key(getattr(strip, "action_slot", None))
                    if strip.action is not None:
                        if owner == self.obj:
                            validate_slot(owner, strip.action, getattr(strip, "action_slot", None))
                        actions[key(strip.action)] = strip.action
        if len(actions) > 16:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Reviewed NLA scope exceeds 16 Actions.")
        for aid, action in actions.items():
            result[("action", aid, "identity")] = (action_token(action), action.name)
            result[("action", aid, "content")] = action_content(action)
            result[("action", aid, "users")] = action_users(bpy, action)
        for path, read in self.extra.items():
            result[path] = read()
        return result

    def gate(self) -> None:
        self.guard.gate()
        object_scope(self.bpy, self.obj)
        _quiet_authority(self.context, self.guard.method)
        if self.snapshot() != self.expected:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Frozen NLA/Action/editor/consumer scope changed; writes and recovery refused.", {"stale_nla_scope": True})

    def step(self, write: Callable, allow=(), verify: Callable | None = None):
        self.gate()
        self.started = True
        result = write()
        after = self.snapshot()
        permitted = allow(result, after) if callable(allow) else allow
        expected = dict(self.expected)
        for path in permitted:
            if path in after:
                expected[path] = after[path]
            else:
                expected.pop(path, None)
        if after != expected or (verify is not None and not verify(result, after)):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Native NLA mutation exceeded its exact expected change; retained for recovery.", {"unexpected_nla_change": True})
        self.expected = after
        _quiet_authority(self.context, self.guard.method)
        return result

    def set(self, owner: Any, field: str, setting: Any, path: tuple, observed: Any = None) -> None:
        desired = setting if observed is None else observed
        if self.expected[path] == desired:
            return
        self.step(lambda: setattr(owner, field, setting), (path,), lambda _result, after: after[path] == desired)

    def summary(self) -> dict:
        tracks = self.obj.animation_data.nla_tracks
        return {"object": self.obj.name, "affected_objects": [self.obj.name, *self.affected],
                "tracks": [{"name": track.name, "native_id": key(track), "strips": [
                    {"name": strip.name, "native_id": key(strip), "type": strip.type,
                     "frame_start": strip.frame_start, "frame_end": strip.frame_end,
                     "action": strip.action.name if strip.action is not None else None,
                     "slot_identifier": getattr(getattr(strip, "action_slot", None), "identifier", None)} for strip in track.strips]} for track in tracks],
                "action_content_digests": [{"name": self.expected[("action", path[1], "identity")][1], "sha256": digest(content)}
                    for path, content in self.expected.items() if len(path) == 3 and path[0] == "action" and path[2] == "content"],
                "action_channels_changed": False, "verification_required": True, "full_animation_acceptance_verified": False,
                "project_saved": False}


class _Editor:
    """Use an existing NLA editor, isolate selection and restore every temporary flag."""

    def __init__(self, proof: _Proof):
        self.proof, self.restore = proof, []
        bpy = proof.bpy
        window = bpy.context.window
        if bpy.app.background or window is None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native NLA transitions/reordering require an existing UI NLA editor.")
        choices = [area for area in bounded(window.screen.areas, 64, "editor areas") if area.type == "NLA_EDITOR"]
        if not choices:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Open an NLA Editor in the current window before this operation.")
        self.window, self.area = window, choices[0]
        self.region = next((region for region in self.area.regions if region.type == "WINDOW"), None)
        if self.region is None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "The NLA editor has no reviewed WINDOW region.")
        self.space = self.area.spaces.active
        proof.extra[("editor", "identity")] = lambda: (key(bpy.context.window), key(self.window.screen), key(self.area), self.area.type, key(self.area.spaces.active), key(self.region))
        proof.extra[("editor", "only_selected")] = lambda: bool(self.space.dopesheet.show_only_selected)
        proof.expected = proof.snapshot()
        proof.editor_baseline = {path: value for path, value in proof.expected.items() if path[0] == "editor"}

    def setting(self, owner, field, setting, path, observed=None):
        old = self.proof.expected[path]
        desired = setting if observed is None else observed
        if old == desired:
            return
        self.restore.append((owner, field, old, path))
        self.proof.set(owner, field, setting, path, observed)

    def isolate(self, track):
        proof, obj, bpy = self.proof, self.proof.obj, self.proof.bpy
        for other in bounded(bpy.context.view_layer.objects, 256, "view-layer objects"):
            path, desired = ("selection", key(other)), other == obj
            if proof.expected[path] != desired:
                old = proof.expected[path]
                self.restore.append((other, "__selection__", old, path))
                proof.step(lambda other=other, desired=desired: other.select_set(desired), (path,), lambda _result, after, path=path, desired=desired: after[path] == desired)
        active_path = ("context", "active")
        old = proof.expected[active_path]
        if old != key(obj):
            self.restore.append((bpy.context.view_layer.objects, "active", old, active_path))
            proof.step(lambda: setattr(bpy.context.view_layer.objects, "active", obj), (active_path,), lambda _result, after: after[active_path] == key(obj))
        self.setting(self.space.dopesheet, "show_only_selected", True, ("editor", "only_selected"))
        for item in obj.animation_data.nla_tracks:
            self.setting(item, "select", item == track, ("track", key(item), "select"))
            for strip in item.strips:
                self.setting(strip, "select", False, ("strip", key(strip), "select"))
        path = ("owner", key(obj), "active_track")
        old = proof.expected[path]
        if old != key(track):
            self.restore.append((obj.animation_data.nla_tracks, "active", old, path))
            proof.step(lambda: setattr(obj.animation_data.nla_tracks, "active", track), (path,), lambda _result, after: after[path] == key(track))

    def operation(self, operator, *, allow, verify, **kwargs):
        proof = self.proof
        with proof.bpy.context.temp_override(window=self.window, area=self.area, region=self.region,
                                              object=proof.obj, active_object=proof.obj,
                                              selected_objects=[proof.obj], selected_editable_objects=[proof.obj]):
            def run():
                if not operator.poll():
                    raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Native NLA operator rejected the isolated editor context.")
                result = operator(**kwargs)
                if result != {"FINISHED"}:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "Native NLA operator did not finish.")
                return result
            return proof.step(run, allow, verify)

    def close(self):
        proof = self.proof
        while self.restore:
            owner, field, old, path = self.restore[-1]
            if field == "__selection__":
                proof.step(lambda owner=owner, old=old: owner.select_set(old), (path,), lambda _result, after, path=path, old=old: after[path] == old)
            elif field == "active":
                if path[0] == "context":
                    candidates = proof.bpy.context.view_layer.objects
                else:
                    candidates = proof.obj.animation_data.nla_tracks
                target = next((item for item in candidates if key(item) == old), None)
                proof.set(owner, field, target, path, old)
            else:
                proof.set(owner, field, old, path)
            self.restore.pop()


def _owned_paths(state: dict, kind: str, native_id: int) -> set[tuple]:
    return {path for path in state if len(path) >= 2 and path[:2] == (kind, native_id)}


def _users_delta(before: dict, after: dict, obj: Any, delta: int) -> bool:
    expected = deepcopy(before)
    expected["users"] += delta
    expected["real_users"] += delta
    records = {record[0]: record for record in expected["references"]}
    previous = records.get(key(obj))
    if previous is None:
        if delta != 1:
            return False
        previous = (key(obj), getattr(obj, "session_uid", None), obj.name, "Object", 0, True)
    count = previous[4]+delta
    if count:
        records[key(obj)] = (*previous[:4], count, previous[5])
    else:
        records.pop(key(obj), None)
    expected["references"] = tuple(sorted(records.values(), key=lambda record: record[0]))
    return after == expected


def _original_restored(proof: _Proof) -> bool:
    try:
        proof.gate()
        return {path: value for path, value in proof.snapshot().items() if path[0] != "editor"} == proof.original
    except Exception:
        return False


def _context_restored(proof: _Proof) -> bool:
    try:
        after = proof.snapshot()
        def context_path(path):
            return (path[0] in {"context", "selection"} or (path[0] == "owner" and path[-1] == "active_track")
                    or (path[0] in {"track", "strip"} and path[-1] in {"select", "active"}))
        before = {path: value for path, value in proof.original.items() if context_path(path)}
        if any(after.get(path) != value for path, value in before.items()):
            return False
        if any(value for path, value in after.items() if context_path(path) and path not in before and path[0] in {"strip", "track"}):
            return False
        return all(after.get(path) == value for path, value in getattr(proof, "editor_baseline", {}).items())
    except Exception:
        return False


def _failure(error, proof, editor=None, **evidence):
    context_cleanup_failed = False
    if editor is not None:
        try:
            editor.close()
        except Exception:
            context_cleanup_failed = True
    restored = _context_restored(proof)
    return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                       "NLA lifecycle failed; inspect exact tracks/strips and finalized recovery checkpoint.",
                       {**(error.context if isinstance(error, BridgeError) else {}), "execution_started": proof.started,
                        "possible_mutation": proof.started, "context_restored": restored,
                        "context_cleanup_failed": context_cleanup_failed, "rollback_verified": False, "verification_required": True, **evidence})


def _retained_child(child: Any) -> dict[str, Any] | None:
    try:
        return None if child is None else {"name": str(child.name)[:63], "native_id": key(child)}
    except Exception:
        return None


def clip_add(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, COMMON | {"track_name", "strip_name", "action_name", "frame_start", "slot_identifier"})
    bpy = require_blender()
    obj = _object(bpy, params)
    track = _track(obj, params.get("track_name"))
    strip_name = _name(params.get("strip_name"), "strip_name")
    if any(strip.name == strip_name for item in obj.animation_data.nla_tracks for strip in item.strips):
        raise invalid_argument("The explicit new strip name is occupied in this owner.")
    if sum(len(item.strips) for item in obj.animation_data.nla_tracks) >= MAX_STRIPS:
        raise invalid_argument("The 64-strip owner budget is exhausted.")
    action = _exact(bounded(bpy.data.actions, 1024, "available Actions"), _name(params.get("action_name"), "action_name"), "Action")
    start = int_param(params, "frame_start", 1, minimum=-100_000, maximum=100_000)
    source_start, source_end = map(float, action.frame_range)
    if not (source_start.is_integer() and source_end.is_integer() and 0 < source_end-source_start <= 100_000
            and -100_000 <= source_start < source_end <= 100_000 and start+source_end-source_start <= 100_000):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Clip creation requires a positive bounded integral Action range.")
    end = start+source_end-source_start
    if any(start < other.frame_end and end > other.frame_start for other in track.strips):
        raise invalid_argument("The requested clip overlaps an existing strip; implicit moving/trimming is forbidden.")
    slots = bounded(getattr(action, "slots", ()), 64, "Action slots")
    requested = params.get("slot_identifier")
    suitable = [slot for slot in slots if slot.target_id_type == "OBJECT"]
    if slots and (len(suitable) != 1 or requested != suitable[0].identifier):
        raise invalid_argument("Reviewed layered clips require one suitable OBJECT slot and its exact explicit slot_identifier.")
    if not slots and requested is not None:
        raise invalid_argument("Legacy Actions do not accept slot_identifier.")
    validate_slot(obj, action, suitable[0] if suitable else None)
    proof = _Proof(context, obj, "nla.clip_add", params.get("affected_objects", []), (action,))
    created = None
    old_users = deepcopy(proof.expected[("action", key(action), "users")])
    old_order = proof.expected[("track", key(track), "strips")]
    insertion = sum(proof.expected[("strip", sid, "frame_start")] < start for sid in old_order)
    def allowed(new, after):
        return _owned_paths(after, "strip", key(new)) | {("track", key(track), "strips"), ("action", key(action), "users")}
    def verify(new, after):
        return (new_clip(new, strip_name, start, end, source_start, source_end, action, suitable[0] if suitable else None)
                and after[("track", key(track), "strips")] == (*old_order[:insertion], key(new), *old_order[insertion:])
                and _users_delta(old_users, after[("action", key(action), "users")], obj, 1))
    def allocate():
        nonlocal created
        created = track.strips.new(strip_name, start, action)
        return created
    try:
        proof.step(allocate, allowed, verify)
        proof.set(created, "select", False, ("strip", key(created), "select"))
        proof.gate()
        return {"added": True, "clip_name": created.name, "copy_or_channel_mapping_performed": False, **proof.summary()}
    except Exception as error:
        recovered = False
        if created is not None:
            try:
                current_users = deepcopy(proof.expected[("action", key(action), "users")])
                removed_paths = _owned_paths(proof.expected, "strip", key(created))
                proof.step(lambda: track.strips.remove(created), removed_paths | {("track", key(track), "strips"), ("action", key(action), "users")},
                           lambda _result, after: after[("track", key(track), "strips")] == old_order and _users_delta(current_users, after[("action", key(action), "users")], obj, -1))
                proof.gate()
                recovered = proof.expected == proof.original
            except Exception:
                recovered = False
        retained = None if recovered else _retained_child(created)
        failure = _failure(error, proof, retained_strip_name=None if retained is None else retained["name"],
                           retained_strip_native_id=None if retained is None else retained["native_id"], requested_strip_name=strip_name)
        failure.context["rollback_verified"] = recovered
        failure.context["possible_mutation"] = proof.started and not recovered
        raise failure from error


def _neighbors(track, left_name, right_name, *, transition_name=None):
    strips = bounded(track.strips, MAX_STRIPS, "NLA strips")
    left, right = _strip(track, left_name), _strip(track, right_name)
    if left.type != "CLIP" or right.type != "CLIP" or left == right or left.mute or right.mute:
        raise invalid_argument("Exact distinct unmuted left/right CLIPs are required.")
    i, j = strips.index(left), strips.index(right)
    if transition_name is None:
        if j != i+1 or not left.frame_end < right.frame_start:
            raise invalid_argument("Transition creation requires adjacent CLIPs with a positive explicit gap.")
        return left, right, None
    transition = _strip(track, transition_name)
    if (j != i+2 or strips[i+1] != transition or transition.type != "TRANSITION"
            or transition.frame_start != left.frame_end or transition.frame_end != right.frame_start):
        raise invalid_argument("An exact TRANSITION between the explicitly named adjacent CLIPs is required.")
    return left, right, transition


def _transition_constructor_name(proof: _Proof) -> str:
    base = proof.bpy.app.translations.pgettext_data("Transition")
    if not isinstance(base, str) or not base or len(base.encode("utf-8")) > 63:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native transition localization exceeds its reviewed name budget.")
    occupied = {strip.name for track in proof.obj.animation_data.nla_tracks for strip in track.strips}
    for index in range(MAX_STRIPS+2):
        suffix = "" if not index else f".{index:03d}"
        candidate = base.encode("utf-8")[:63-len(suffix)].decode("utf-8", errors="ignore")+suffix
        if candidate not in occupied:
            return candidate
    raise invalid_argument("Native transition constructor name could not be determined within its bounded scope.")


def transition_add(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, COMMON | {"track_name", "left_strip", "right_strip", "new_name"})
    obj = _object(require_blender(), params)
    track = _track(obj, params.get("track_name"))
    left, right, _ = _neighbors(track, params.get("left_strip"), params.get("right_strip"))
    new_name = _name(params.get("new_name"), "new_name")
    if any(strip.name == new_name for item in obj.animation_data.nla_tracks for strip in item.strips):
        raise invalid_argument("The explicit transition name is already occupied.")
    if sum(len(item.strips) for item in obj.animation_data.nla_tracks) >= MAX_STRIPS:
        raise invalid_argument("The 64-strip owner budget is exhausted.")
    proof = _Proof(context, obj, "nla.transition_add", params.get("affected_objects", []))
    editor, created = None, None
    constructor_name = _transition_constructor_name(proof)
    try:
        editor = _Editor(proof)
        editor.isolate(track)
        for strip in (left, right):
            editor.setting(strip, "select", True, ("strip", key(strip), "select"))
        before_order = proof.expected[("track", key(track), "strips")]
        before = set(before_order)
        insertion = before_order.index(key(left))+1
        def allowed(_result, after):
            nonlocal created
            candidates = [strip for strip in track.strips if key(strip) not in before]
            if len(candidates) != 1:
                return ()
            created = candidates[0]
            return _owned_paths(after, "strip", key(created)) | {("track", key(track), "strips")}
        editor.operation(proof.bpy.ops.nla.transition_add, allow=allowed,
                         verify=lambda _result, after: created is not None and new_transition(created, constructor_name, left.frame_end, right.frame_start)
                         and after[("track", key(track), "strips")] == (*before_order[:insertion], key(created), *before_order[insertion:]))
        proof.set(created, "name", new_name, ("strip", key(created), "name"))
        proof.set(created, "select", False, ("strip", key(created), "select"))
        editor.close()
        proof.gate()
        return {"added": True, "transition_name": created.name, "native_strip_type": created.type,
                "transition_range": [created.frame_start, created.frame_end], "context_restored": True,
                "neighbor_identities_preserved": True, **proof.summary()}
    except Exception as error:
        recovered = False
        if created is not None:
            try:
                paths = _owned_paths(proof.expected, "strip", key(created)) | {("track", key(track), "strips")}
                proof.step(lambda: track.strips.remove(created), paths)
                recovered = True
            except Exception:
                recovered = False
        retained = None if recovered else _retained_child(created)
        failure = _failure(error, proof, editor, retained_transition_name=None if retained is None else retained["name"],
                           retained_transition_native_id=None if retained is None else retained["native_id"], requested_transition_name=new_name)
        failure.context["transition_allocation_removed"] = recovered
        original_restored = recovered and failure.context["context_restored"] and _original_restored(proof)
        failure.context["rollback_verified"] = original_restored
        failure.context["possible_mutation"] = proof.started and not original_restored
        raise failure from error


def transition_remove(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, COMMON | {"track_name", "left_strip", "right_strip", "transition_name", "confirm"})
    if params.get("confirm") is not True:
        raise invalid_argument("confirm=true is required for exact TRANSITION removal.")
    obj = _object(require_blender(), params)
    track = _track(obj, params.get("track_name"))
    left, right, transition = _neighbors(track, params.get("left_strip"), params.get("right_strip"), transition_name=params.get("transition_name"))
    proof = _Proof(context, obj, "nla.transition_remove", params.get("affected_objects", []))
    before = proof.expected[("track", key(track), "strips")]
    removed_id, name = key(transition), transition.name
    try:
        proof.step(lambda: track.strips.remove(transition), _owned_paths(proof.expected, "strip", removed_id) | {("track", key(track), "strips")},
                   lambda _result, after: after[("track", key(track), "strips")] == tuple(sid for sid in before if sid != removed_id))
        proof.gate()
        return {"removed": True, "transition_name": name, "removed_native_id": removed_id,
                "neighbor_native_ids": [key(left), key(right)], "context_restored": True, **proof.summary()}
    except Exception as error:
        raise _failure(error, proof, removed_transition_name=name, explicit_native_checkpoint_recovery_required=True) from error


def _reorder(proof, editor, desired):
    path = ("owner", key(proof.obj), "order")
    tracks = proof.obj.animation_data.nla_tracks
    for index, native_id in enumerate(desired):
        while proof.expected[path].index(native_id) > index:
            moving = next(track for track in tracks if key(track) == native_id)
            for track in tracks:
                proof.set(track, "select", track == moving, ("track", key(track), "select"))
            proof.set(tracks, "active", moving, ("owner", key(proof.obj), "active_track"), native_id)
            old = list(proof.expected[path])
            at = old.index(native_id)
            old[at-1], old[at] = old[at], old[at-1]
            editor.operation(proof.bpy.ops.anim.channels_move, direction="DOWN", allow=(path,),
                             verify=lambda _result, after, expected=tuple(old): after[path] == expected)


def track_reorder(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, COMMON | {"track_names"})
    obj = _object(require_blender(), params)
    tracks = bounded(obj.animation_data.nla_tracks, MAX_TRACKS, "NLA tracks")
    names = params.get("track_names")
    if (not isinstance(names, list) or not 1 <= len(names) <= MAX_TRACKS or any(not isinstance(name, str) for name in names)
            or len(set(names)) != len(names) or set(names) != {track.name for track in tracks} or len(names) != len(tracks)):
        raise invalid_argument("track_names must provide the exact complete unique NLA track permutation, bottom to top.")
    if any(track.lock for track in tracks):
        raise invalid_argument("Unlock every reordered track explicitly before permutation.")
    desired = tuple(key(_exact(tracks, name, "track")) for name in names)
    proof = _Proof(context, obj, "nla.track_reorder", params.get("affected_objects", []))
    original = proof.expected[("owner", key(obj), "order")]
    editor = None
    selection, active = None, None
    try:
        editor = _Editor(proof)
        editor.isolate(tracks[0])
        selection = {key(track): bool(track.select) for track in tracks}
        active = obj.animation_data.nla_tracks.active
        _reorder(proof, editor, desired)
        for track in tracks:
            proof.set(track, "select", selection[key(track)], ("track", key(track), "select"))
        proof.set(obj.animation_data.nla_tracks, "active", active, ("owner", key(obj), "active_track"), key(active))
        editor.close()
        proof.gate()
        return {"reordered": original != desired, "track_names_bottom_to_top": names,
                "native_operator": "anim.channels_move", "track_and_strip_identities_preserved": True,
                "context_restored": True, **proof.summary()}
    except Exception as error:
        recovered = False
        if editor is not None:
            try:
                _reorder(proof, editor, original)
                if selection is not None:
                    for track in tracks:
                        proof.set(track, "select", selection[key(track)], ("track", key(track), "select"))
                    proof.set(obj.animation_data.nla_tracks, "active", active, ("owner", key(obj), "active_track"), key(active))
                recovered = True
            except Exception:
                recovered = False
        failure = _failure(error, proof, editor, original_order_restored=recovered)
        original_restored = recovered and failure.context["context_restored"] and _original_restored(proof)
        failure.context["rollback_verified"] = original_restored
        failure.context["possible_mutation"] = proof.started and not original_restored
        raise failure from error


def register_tools(registry: Any) -> None:
    for name, handler in (("nla.clip_add", clip_add), ("nla.transition_add", transition_add),
                          ("nla.transition_remove", transition_remove), ("nla.track_reorder", track_reorder)):
        registry.register(name, handler, toolset="animation_layers", modifies=True, permissions=(Permission.EDIT_ANIMATION,),
                          description=handler.__doc__ or "Bounded exact NLA lifecycle; preserve Action content and native identities, verify evaluated playback and recovery.")
