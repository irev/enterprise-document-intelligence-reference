"""Apply immutable PostgreSQL migrations once, with checksum verification."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

MIGRATION_GLOB = "[0-9][0-9][0-9][0-9]_*.sql"
LEDGER_SCHEMA = "control_plane"
LEDGER_TABLE = "schema_migration"


def migration_files(directory: Path) -> list[Path]:
    files = sorted(directory.glob(MIGRATION_GLOB))
    versions = [path.name.split("_", 1)[0] for path in files]
    if len(versions) != len(set(versions)):
        raise RuntimeError("DUPLICATE_MIGRATION_VERSION")
    return files


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_migrations(dsn: str, directory: Path) -> None:
    import psycopg

    files = migration_files(directory)
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {LEDGER_SCHEMA}")
            cursor.execute(
                f"""CREATE TABLE IF NOT EXISTS {LEDGER_SCHEMA}.{LEDGER_TABLE} (
                    version text PRIMARY KEY,
                    filename text NOT NULL UNIQUE,
                    sha256 text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
        connection.commit()

        for path in files:
            version = path.name.split("_", 1)[0]
            digest = checksum(path)
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""SELECT filename, sha256
                            FROM {LEDGER_SCHEMA}.{LEDGER_TABLE}
                            WHERE version = %s""",
                        (version,),
                    )
                    applied = cursor.fetchone()
                    if applied is not None:
                        if applied != (path.name, digest):
                            raise RuntimeError(f"MIGRATION_CHECKSUM_MISMATCH:{version}")
                        continue

                    cursor.execute(path.read_text(encoding="utf-8"))
                    cursor.execute(
                        f"""INSERT INTO {LEDGER_SCHEMA}.{LEDGER_TABLE}
                            (version, filename, sha256) VALUES (%s, %s, %s)""",
                        (version, path.name, digest),
                    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--directory", type=Path, default=Path("migrations"))
    args = parser.parse_args()
    apply_migrations(args.dsn, args.directory)


if __name__ == "__main__":
    main()
