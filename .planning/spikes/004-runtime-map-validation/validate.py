"""Spike 004 — runtime-map-validation.

Question: if we replace `OverwatchMap = Literal[...]` with plain `str` + a runtime check
against `maps.names`, do we still reject unknown maps with a *clear* error? And what,
concretely, does the static-typing loss look like?

Run:
    uv run --env-file .env.local --with asyncpg --with msgspec python validate.py

Connects to the real local Docker Postgres (63 real map names in maps.names).
"""

from __future__ import annotations

import asyncio
import difflib
import os
from typing import Literal

import asyncpg
import msgspec

# ---------------------------------------------------------------------------
# A tiny slice of the real OverwatchMap Literal, to demonstrate OLD behaviour.
# (The real one has 73 entries hardcoded in libs/sdk/.../maps.py.)
# ---------------------------------------------------------------------------
OverwatchMapLiteral = Literal["Hanamura", "Circuit Royal", "Ayutthaya", "Busan"]


class OldRequest(msgspec.Struct):
    """How map_name is validated TODAY: a closed Literal, checked by msgspec at decode."""

    code: str
    map_name: OverwatchMapLiteral


class NewRequest(msgspec.Struct):
    """Proposed: plain str at the boundary, validated against the DB at runtime."""

    code: str
    map_name: str


class UnknownMapError(Exception):
    """Raised when a map name is not present in maps.names. The runtime equivalent of
    the msgspec Literal rejection — but we control the message."""


def line(c: str = "─") -> str:
    return c * 70


async def load_known_maps(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT name FROM maps.names")
    return {r["name"] for r in rows}


def validate_map_name(name: str, known: set[str]) -> str:
    """Runtime validation. Returns the canonical name or raises a clear error,
    with a 'did you mean' suggestion that the Literal could never give."""
    if name in known:
        return name
    suggestions = difflib.get_close_matches(name, known, n=3, cutoff=0.6)
    hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
    raise UnknownMapError(f"'{name}' is not a known Overwatch map.{hint}")


async def main() -> None:
    print(line("="))
    print(" SPIKE 004 — runtime-map-validation")
    print(line("="))

    # --- OLD: msgspec Literal validation -----------------------------------
    print("\n[1] OLD behaviour — Literal validated by msgspec at decode time\n")
    for payload in (b'{"code":"AAAAA","map_name":"Hanamura"}',
                    b'{"code":"AAAAA","map_name":"Hanamuraa"}'):  # typo
        try:
            req = msgspec.json.decode(payload, type=OldRequest)
            print(f"  ACCEPT  {payload.decode()}  ->  {req.map_name!r}")
        except msgspec.ValidationError as e:
            print(f"  REJECT  {payload.decode()}")
            print(f"          msgspec says: {e}")

    # --- NEW: str + runtime DB validation ----------------------------------
    print("\n[2] NEW behaviour — str at boundary, validated against maps.names\n")
    conn = await asyncpg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
    )
    try:
        known = await load_known_maps(conn)
        print(f"  loaded {len(known)} real map names from maps.names\n")
        # Note: a brand-new map ("Throne of Anubis") decodes fine as str — proving the
        # boundary no longer blocks unknown maps. The DB is the single gate.
        tests = ["Hanamura", "Hanamuraa", "Circ Royal", "Throne of Anubis"]
        for name in tests:
            payload = msgspec.json.encode({"code": "AAAAA", "map_name": name})
            req = msgspec.json.decode(payload, type=NewRequest)  # always decodes
            try:
                canon = validate_map_name(req.map_name, known)
                print(f"  ACCEPT  {name!r}  ->  {canon!r}")
            except UnknownMapError as e:
                print(f"  REJECT  {name!r}")
                print(f"          {e}")
    finally:
        await conn.close()

    print("\n" + line())
    print(" Findings:")
    print(" - str field decodes ANY string -> the request boundary no longer blocks")
    print("   new maps. That is exactly what unblocks 'appears automatically'.")
    print(" - Runtime validation reproduces the rejection AND adds 'did you mean'")
    print("   suggestions the closed Literal could never provide.")
    print(" - The gate moves from the type system (compile-time) to the DB (runtime).")
    print(line())


if __name__ == "__main__":
    asyncio.run(main())
