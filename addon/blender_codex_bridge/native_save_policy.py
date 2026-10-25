# SPDX-License-Identifier: GPL-3.0-or-later
"""Runtime-only local authority for ordinary native save side effects."""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

POLICY_VERSION = "stock_native_save_effects_v1"
PERMISSION = "NATIVE_SAVE_EFFECTS"


@dataclass(frozen=True, slots=True)
class GrantStatement:
    generation: str
    epoch: int
    expires: float
    policy: str = POLICY_VERSION


class NativeSaveGrant:
    """A local session grant; serialized booleans/epochs cannot arm it.

    Trusted Python inside Blender is not an adversarial security boundary.
    """

    __slots__ = ("_authority", "_epoch", "_generation", "_sealed", "_statement", "_thread")

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise ValueError("Native save grant state is owned by its local lifecycle methods.")
        object.__setattr__(self, name, value)

    def __init__(self, generation: str, authority: object):
        if (threading.current_thread() is not threading.main_thread()
                or type(authority) is not object or type(generation) is not str
                or not generation or len(generation) > 128
                or any(ord(c) < 32 for c in generation)):
            raise ValueError("Native save permission requires an exact local main-thread owner and generation.")
        self._thread, self._authority, self._generation = threading.get_ident(), authority, generation
        self._epoch, self._statement = 0, None
        self._sealed = True

    @property
    def generation(self):
        return self._generation

    def _main(self):
        if (threading.current_thread() is not threading.main_thread()
                or threading.get_ident() != self._thread):
            raise ValueError("Native save permission changes require the owning main thread.")

    @staticmethod
    def _now(value):
        value = time.monotonic() if value is None else value
        if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
            raise ValueError("Native save permission requires a finite monotonic time.")
        return value

    def arm(self, authority: object, seconds: int, *, now: float | None = None):
        self._main()
        if authority is not self._authority or type(seconds) is not int or not 1 <= seconds <= 1800:
            raise ValueError("Only the local owner may arm native save effects for 1..1800 seconds.")
        expires = self._now(now) + seconds
        object.__setattr__(self, "_epoch", self._epoch + 1)
        object.__setattr__(self, "_statement", GrantStatement(self.generation, self._epoch, expires))
        return self._statement

    def revoke(self):
        self._main()
        object.__setattr__(self, "_epoch", self._epoch + 1)
        object.__setattr__(self, "_statement", None)

    def active(self, *, now: float | None = None) -> bool:
        value = self._statement
        return (type(value) is GrantStatement and value.generation == self.generation
                and value.epoch == self._epoch and value.policy == POLICY_VERSION
                and self._now(now) < value.expires)

    def statement(self) -> GrantStatement:
        if not self.active():
            raise ValueError("Native save effects are disarmed or expired.")
        assert self._statement is not None
        return self._statement

    def check(self, original: GrantStatement):
        if self.statement() is not original:
            raise ValueError("The native save permission epoch changed.")

    def status(self):
        value = self._statement
        now = self._now(None)
        return {"armed": self.active(now=now), "policy_version": POLICY_VERSION,
                "remaining_seconds": max(0, math.ceil(value.expires - now)) if value else 0,
                "session_generation": self.generation,
                "normal_native_external_effects_inventory_complete": False}
