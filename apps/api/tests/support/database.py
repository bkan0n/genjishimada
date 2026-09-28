"""A migrated, seeded baseline shared only within one pytest worker.

Every database test restores the baseline, including reference/configuration
rows that tests can edit. Connections and pools remain function scoped because
asyncpg connections belong to the event loop that created them.
"""

from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

API_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TableSnapshot:
    name: sql.Identifier
    columns: sql.Composed
    data: bytes


@dataclass(frozen=True)
class DatabaseBaseline:
    tables: tuple[sql.Identifier, ...]
    populated: tuple[TableSnapshot, ...]
    sequences: sql.Composed

    @classmethod
    def capture(cls, connection: psycopg.Connection) -> "DatabaseBaseline":
        """Capture actual migration output instead of maintaining a second seed list."""
        tables = []
        populated = []
        rows = connection.execute(
            "SELECT schemaname, tablename FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
            "AND schemaname NOT LIKE 'pg_%' ORDER BY schemaname, tablename"
        ).fetchall()
        for schema, table in rows:
            name = sql.Identifier(schema, table)
            tables.append(name)
            if not connection.execute(sql.SQL("SELECT EXISTS (SELECT FROM {})").format(name)).fetchone()[0]:
                continue
            columns = sql.SQL(", ").join(
                sql.Identifier(row[0])
                for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s AND is_generated = 'NEVER' "
                    "ORDER BY ordinal_position",
                    (schema, table),
                )
            )
            with connection.cursor().copy(
                sql.SQL("COPY {} ({}) TO STDOUT (FORMAT BINARY)").format(name, columns)
            ) as copy:
                data = b"".join(bytes(block) for block in copy)
            populated.append(TableSnapshot(name, columns, data))

        resets = []
        for schema, sequence in connection.execute(
            "SELECT schemaname, sequencename FROM pg_sequences "
            "WHERE schemaname NOT LIKE 'pg_%' ORDER BY schemaname, sequencename"
        ).fetchall():
            name = sql.Identifier(schema, sequence)
            value, called = connection.execute(sql.SQL("SELECT last_value, is_called FROM {}").format(name)).fetchone()
            resets.append(
                sql.SQL("SELECT setval({}::regclass, {}, {});").format(
                    sql.Literal(name.as_string(connection)), sql.Literal(value), sql.Literal(called)
                )
            )
        connection.commit()
        return cls(tuple(tables), tuple(populated), sql.SQL("\n").join(resets))

    def restore(self, connection: psycopg.Connection) -> None:
        """Reset rows and sequence state before any test-owned connection opens."""
        with connection.transaction():
            connection.execute("SET LOCAL lock_timeout = '5s'; SET LOCAL statement_timeout = '30s'")
            connection.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(sql.SQL(", ").join(self.tables)))
            # COPY restores a known-valid snapshot. Suppress triggers only while
            # restoring it, so FK ordering and update-timestamp triggers cannot
            # change the saved baseline. The test itself uses normal constraints.
            connection.execute("SET LOCAL session_replication_role = replica")
            for table in self.populated:
                with connection.cursor().copy(
                    sql.SQL("COPY {} ({}) FROM STDIN (FORMAT BINARY)").format(table.name, table.columns)
                ) as copy:
                    copy.write(table.data)
            if self.sequences:
                connection.execute(self.sequences, prepare=False)


def migrate(connection: psycopg.Connection) -> None:
    """Apply the same migration and seed files used by the existing suite once."""
    for directory in (API_ROOT / "migrations", API_ROOT / "seeds"):
        for path in sorted(directory.glob("*.sql")):
            try:
                connection.execute(path.read_text(), prepare=False)
                connection.commit()
            except Exception as exc:
                connection.rollback()
                raise RuntimeError(f"Failed applying SQL file: {path}") from exc
