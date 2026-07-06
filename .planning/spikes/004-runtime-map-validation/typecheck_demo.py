"""Spike 004 — what static type-safety do we actually lose?

This file is meant to be type-checked, not run. basedpyright should flag the Literal
typo and stay silent on the str typo — that delta IS the cost of going runtime.

Check:
    uv run --with basedpyright basedpyright .planning/spikes/004-runtime-map-validation/typecheck_demo.py
"""

from typing import Literal

OverwatchMap = Literal["Hanamura", "Circuit Royal", "Ayutthaya"]


def submit_with_literal(map_name: OverwatchMap) -> None: ...


def submit_with_str(map_name: str) -> None: ...


# TODAY: a hardcoded typo in code is caught at type-check time.
submit_with_literal("Hanamuraa")  # expect: basedpyright ERROR (not assignable to Literal)

# PROPOSED: the same typo sails through — only the runtime DB check (validate.py) catches it.
submit_with_str("Hanamuraa")  # expect: NO error
