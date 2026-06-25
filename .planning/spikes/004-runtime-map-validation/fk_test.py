"""Spike 004 — FK integrity layer.

The runtime check (validate.py) lives in the service layer. But the exploration found
core.maps.map_name is plain `text` with NO foreign key to maps.names — so a bug or a
direct write could still orphan a map. This script tests adding the missing FK as a
defence-in-depth backstop, and surfaces the migration gotcha: the FK can only be added
if no existing rows are already orphaned.

Everything runs inside a transaction that is ROLLED BACK — the real DB is never mutated.

Run:
    uv run --env-file .env.local --with asyncpg python fk_test.py
"""

from __future__ import annotations

import asyncio
import os

import asyncpg


def line(c: str = "─") -> str:
    return c * 70


async def main() -> None:
    print(line("="))
    print(" SPIKE 004 — FK integrity (rolled back, DB untouched)")
    print(line("="))

    conn = await asyncpg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
    )
    try:
        # --- Pre-flight: are there orphaned map_names already? --------------
        orphans = await conn.fetch(
            """
            SELECT DISTINCT m.map_name
            FROM core.maps m
            LEFT JOIN maps.names n ON n.name = m.map_name
            WHERE n.name IS NULL
            ORDER BY m.map_name
            """
        )
        print(f"\n[1] Orphan check: {len(orphans)} distinct map_name(s) in core.maps "
              f"NOT in maps.names")
        if orphans:
            print("    GOTCHA: the FK migration would FAIL until these are reconciled:")
            for r in orphans:
                print(f"      - {r['map_name']!r}")
        else:
            print("    clean — FK can be added directly.")

        tr = conn.transaction()
        await tr.start()
        try:
            # --- Add the FK (only succeeds if no orphans) -------------------
            print("\n[2] Adding FK core.maps.map_name -> maps.names.name ...")
            try:
                await conn.execute(
                    """
                    ALTER TABLE core.maps
                    ADD CONSTRAINT maps_map_name_names_fk
                    FOREIGN KEY (map_name) REFERENCES maps.names (name)
                    ON UPDATE CASCADE
                    """
                )
                print("    OK — constraint added.")
            except asyncpg.PostgresError as e:
                print(f"    FAILED — {type(e).__name__}: {e}")
                print("    (this is the orphan gotcha — handle in the real migration)")
                await tr.rollback()
                return

            # --- Try inserting a bad map_name -> should be rejected ---------
            # GOTCHA: a constraint error aborts the whole transaction. To catch it
            # and keep going (as the real service would), wrap it in a SAVEPOINT.
            print("\n[3] INSERT into core.maps with an unknown map_name ...")
            try:
                async with conn.transaction():  # nested -> SAVEPOINT
                    await conn.execute(
                        """
                        INSERT INTO core.maps (code, map_name, category, checkpoints,
                                               difficulty, raw_difficulty)
                        VALUES ('ZZZZZ', 'Definitely Not A Map', 'Classic', 3, 'Easy', 1.0)
                        """
                    )
                print("    UNEXPECTED — insert succeeded (FK not enforcing?)")
            except asyncpg.ForeignKeyViolationError as e:
                print(f"    REJECTED by FK — {e.constraint_name or 'fk'}: {e}")
                print("    (savepoint absorbed it; outer transaction still usable)")

            # --- Insert a good one to prove the happy path still works ------
            good = await conn.fetchval("SELECT name FROM maps.names LIMIT 1")
            print(f"\n[4] INSERT with a known map_name ({good!r}) ...")
            await conn.execute(
                """
                INSERT INTO core.maps (code, map_name, category, checkpoints,
                                       difficulty, raw_difficulty)
                VALUES ('ZZZZY', $1, 'Classic', 3, 'Easy', 1.0)
                """,
                good,
            )
            print("    OK — accepted.")
        finally:
            await tr.rollback()
            print("\n[5] transaction rolled back — core.maps unchanged.")
    finally:
        await conn.close()

    print("\n" + line())
    print(" Findings: FK is a real backstop, but the migration must reconcile any")
    print(" pre-existing orphan map_names first (see [1]).")
    print(line())


if __name__ == "__main__":
    asyncio.run(main())
