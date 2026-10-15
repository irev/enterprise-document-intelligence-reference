import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from edi_reference.adapters.document_images import ImagePreparationLimits, PdfiumDocumentImagePreparer
from edi_reference.adapters.sqlite_image_derivation import SqliteImageDerivationRepository
from edi_reference.application.image_derivation import prepare_image_derivation
from edi_reference.application.lineage import ObservationAccessDenied
from edi_reference.domain.lineage import ProcessingRunBinding, SourceObservation
from test_document_images import pdf


@pytest.fixture
def context(tmp_path):
    path = tmp_path / "state.db"
    repo = SqliteImageDerivationRepository(path)
    content = pdf(3)
    digest = hashlib.sha256(content).hexdigest()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    observation = SourceObservation("obs-source", "doc-synthetic", "tenant-a", "app-a", digest,
                                    len(content), "application/pdf", now)
    binding = ProcessingRunBinding("run-1", observation.document_id, "tenant-a", "app-a", "obs-source", digest, now)
    options = dict(observation=observation, binding=binding, preparer=PdfiumDocumentImagePreparer(),
                   repository=repo, tenant_id="tenant-a", application_id="app-a", page_numbers=(3, 1))
    yield content, options, path
    repo.close()


def test_real_render_persist_restart_and_stable_retry(context):
    content, options, path = context
    first = prepare_image_derivation(content, **options)
    assert not first.prepared.complete
    assert [p.source_page_number for p in first.prepared.pages] == [3, 1]
    assert dict(first.prepared.recipe)["algorithm"] == "pdfium-jpeg/v1"
    assert {"pypdfium2", "pdfium", "pillow", "dpi", "max_pages"} <= dict(first.prepared.recipe).keys()
    assert prepare_image_derivation(content, **options) == first
    second_connection = SqliteImageDerivationRepository(path)
    try:
        loaded = second_connection.get("run-1", tenant_id="tenant-a", application_id="app-a")
        assert loaded == first
        ids = [loaded.image_observation_id(p) for p in loaded.prepared.pages]
        assert len(set(ids)) == 2
        assert ids == [first.image_observation_id(p) for p in first.prepared.pages]
    finally:
        second_connection.close()


@pytest.mark.parametrize("changes", [{"tenant_id": "tenant-b"}, {"application_id": "app-b"}])
def test_cross_scope_read_and_prepare_rejected(context, changes):
    content, options, _ = context
    prepare_image_derivation(content, **options)
    scope = dict(tenant_id="tenant-a", application_id="app-a") | changes
    assert options["repository"].get("run-1", **scope) is None
    with pytest.raises(ObservationAccessDenied):
        prepare_image_derivation(content, **(options | changes))


@pytest.mark.parametrize("field, value", [
    ("document_id", "other"), ("observation_id", "other"), ("tenant_id", "other"),
    ("application_id", "other"), ("observation_sha256", "0" * 64),
])
def test_binding_mismatch_before_render(context, field, value):
    content, options, _ = context
    with pytest.raises(ValueError, match="DERIVATION_BINDING_MISMATCH"):
        prepare_image_derivation(content, **(options | {"binding": replace(options["binding"], **{field: value})}))


def test_changed_source_before_render_or_persistence(context):
    content, options, _ = context

    class NoRender:
        def prepare(self, *args, **kwargs):
            pytest.fail("mismatched source must not render")

    with pytest.raises(ValueError, match="DERIVATION_SOURCE_MISMATCH"):
        prepare_image_derivation(content + b"changed", **(options | {"preparer": NoRender()}))
    assert options["repository"].get("run-1", tenant_id="tenant-a", application_id="app-a") is None


@pytest.mark.parametrize("change", ["settings", "selection", "version"])
def test_retry_cannot_overwrite_recipe_or_selection(context, change):
    content, options, _ = context
    first = prepare_image_derivation(content, **options)
    if change == "settings":
        options = options | {"preparer": PdfiumDocumentImagePreparer(ImagePreparationLimits(dpi=72))}
    elif change == "selection":
        options = options | {"page_numbers": (1, 3)}
    else:
        class ChangedVersion:
            def prepare(self, *args, **kwargs):
                return replace(first.prepared, recipe=first.prepared.recipe + (("new-version", "2"),))
        options = options | {"preparer": ChangedVersion()}
    with pytest.raises(ValueError, match="IMAGE_DERIVATION_CONFLICT"):
        prepare_image_derivation(content, **options)
    assert options["repository"].get("run-1", tenant_id="tenant-a", application_id="app-a") == first


def test_reprocess_creates_new_observations_and_preserves_original(context):
    content, options, _ = context
    first = prepare_image_derivation(content, **options)
    second = prepare_image_derivation(content, **(options | {"binding": replace(options["binding"],
                                                                                 processing_run_id="run-2")}))
    assert first.image_observation_id(first.prepared.pages[0]) != second.image_observation_id(second.prepared.pages[0])
    assert options["repository"].get("run-1", tenant_id="tenant-a", application_id="app-a") == first


@pytest.mark.parametrize("table", ["image_derivation_batches", "image_derivation_pages"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_database_rejects_mutation(context, table, operation):
    content, options, path = context
    prepare_image_derivation(content, **options)
    with sqlite3.connect(path) as db:
        sql = f"DELETE FROM {table}" if operation == "DELETE" else f"UPDATE {table} SET tenant_id='other'"
        with pytest.raises(sqlite3.IntegrityError, match="IMAGE_DERIVATION_IMMUTABLE"):
            db.execute(sql)


def test_atomic_rollback_when_second_page_fails(context):
    content, options, path = context
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TRIGGER synthetic_failure BEFORE INSERT ON image_derivation_pages
                      WHEN NEW.ordinal=1 BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
        prepare_image_derivation(content, **options)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM image_derivation_batches").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM image_derivation_pages").fetchone()[0] == 0


def test_forged_image_digest_rejected_before_save(context):
    content, options, _ = context
    prepared = options["preparer"].prepare(content, media_type="application/pdf")

    class Forged:
        def prepare(self, *args, **kwargs):
            return replace(prepared, pages=(replace(prepared.pages[0], content=b"changed"),))

    with pytest.raises(ValueError, match="DERIVATION_IMAGE_DIGEST_MISMATCH"):
        prepare_image_derivation(content, **(options | {"preparer": Forged()}))


def test_persisted_derived_image_is_compatible_with_vision_evidence(context):
    from test_openai_vision import Transport, analyzer

    content, options, _ = context
    prepare_image_derivation(content, **options)
    saved = options["repository"].get("run-1", tenant_id="tenant-a", application_id="app-a")
    page = saved.prepared.pages[0]
    result = analyzer(Transport()).analyze(page.content, media_type=page.media_type,
                                         observation_id=saved.image_observation_id(page))
    evidence = result.classification.evidence[0]
    assert evidence.observation_id == saved.image_observation_id(page)
    assert evidence.observation_sha256 == page.sha256
    assert evidence.page_number == 1 and page.source_page_number == 3
    assert evidence.observation_sha256 != saved.binding.observation_sha256


def test_identical_bytes_across_tenants_get_distinct_image_identities(context):
    content, options, _ = context
    first = prepare_image_derivation(content, **options)
    second = prepare_image_derivation(content, **(options | {
        "tenant_id": "tenant-b",
        "observation": replace(options["observation"], tenant_id="tenant-b"),
        "binding": replace(options["binding"], tenant_id="tenant-b"),
    }))
    assert first.image_observation_id(first.prepared.pages[0]) != second.image_observation_id(second.prepared.pages[0])
    assert options["repository"].get("run-1", tenant_id="tenant-a", application_id="app-a") == first
    assert options["repository"].get("run-1", tenant_id="tenant-b", application_id="app-a") == second


def test_stored_image_corruption_is_detected(context):
    content, options, path = context
    prepare_image_derivation(content, **options)
    with sqlite3.connect(path) as db:
        # Simulate storage corruption outside the supported immutable interface.
        db.execute("DROP TRIGGER image_pages_no_update")
        db.execute("UPDATE image_derivation_pages SET content=? WHERE ordinal=0", (b"corrupt",))
    with pytest.raises(ValueError, match="IMAGE_DERIVATION_CORRUPT"):
        options["repository"].get("run-1", tenant_id="tenant-a", application_id="app-a")
