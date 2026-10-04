from pathlib import Path

import pytest

from scripts.apply_migrations import checksum, migration_files


def test_migration_files_are_discovered_in_version_order():
    files = migration_files(Path("migrations"))
    assert [path.name for path in files] == sorted(path.name for path in files)
    assert [path.name for path in files][:2] == [
        "0001_control_plane.sql",
        "0002_inbound_outbox.sql",
    ]


def test_duplicate_migration_version_is_rejected(tmp_path):
    (tmp_path / "0001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0001_second.sql").write_text("SELECT 2;", encoding="utf-8")

    with pytest.raises(RuntimeError, match="DUPLICATE_MIGRATION_VERSION"):
        migration_files(tmp_path)


def test_migration_checksum_changes_with_content(tmp_path):
    migration = tmp_path / "0001_example.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    original = checksum(migration)
    migration.write_text("SELECT 2;", encoding="utf-8")
    assert checksum(migration) != original
