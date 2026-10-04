import os
from pathlib import Path

import pytest

from scripts.apply_migrations import apply_migrations, migration_files


DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def test_migration_runner_is_rerunnable_and_records_checksums():
    import psycopg

    migrations = migration_files(Path("migrations"))
    apply_migrations(DSN, Path("migrations"))
    apply_migrations(DSN, Path("migrations"))

    with psycopg.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT version, filename, sha256
                   FROM control_plane.schema_migration
                   ORDER BY version"""
            )
            rows = cursor.fetchall()

    expected_versions = [path.name.split("_", 1)[0] for path in migrations]
    assert [row[0] for row in rows] == expected_versions
    assert all(len(row[2]) == 64 for row in rows)
