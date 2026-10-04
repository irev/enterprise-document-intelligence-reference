from datetime import UTC, datetime

import pytest

from edi_reference.application.structure import InvalidDocumentStructure, validate_structured_document
from edi_reference.domain.document_structure import (
    BoundingBox, PageStructure, StructuredDocument, TableBlock, TableCell, TextBlock,
)
from edi_reference.domain.lineage import ScopedObservation


def obs():
    return ScopedObservation(
        observation_id="obs-1", document_id="doc-1", tenant_id="tenant-a",
        application_id="app-a", sha256="a" * 64, byte_length=10,
        detected_media_type="application/pdf", observed_at=datetime(2026, 10, 4, tzinfo=UTC),
    )


def test_valid_structure_preserves_evidence_coordinates():
    doc = StructuredDocument(
        observation_id="obs-1", observation_sha256="a" * 64,
        component="synthetic-layout", component_version="1",
        pages=(PageStructure(
            page_number=1, width=595, height=842,
            text_blocks=(TextBlock("b1", "Invoice", BoundingBox(.1,.1,.3,.2), 0, .99),),
            tables=(TableBlock(
                "t1", BoundingBox(.1,.3,.9,.8), 1,
                (TableCell(0,0,"Item",BoundingBox(.1,.3,.4,.4)),),
            ),),
        ),),
    )
    validate_structured_document(obs(), doc)
    assert doc.pages[0].text_blocks[0].bbox.x0 == .1


def test_bbox_must_be_normalized_and_ordered():
    with pytest.raises(ValueError, match="INVALID_NORMALIZED_BOUNDING_BOX"):
        BoundingBox(.8, .1, .2, .3)


def test_structure_must_match_observation_digest():
    doc = StructuredDocument("obs-1", "b"*64, (), "parser", "1")
    with pytest.raises(InvalidDocumentStructure, match="OBSERVATION_DIGEST_MISMATCH"):
        validate_structured_document(obs(), doc)


def test_block_ids_are_unique_across_document():
    block = TextBlock("same", "x", BoundingBox(0,0,1,1), 0)
    doc = StructuredDocument(
        "obs-1", "a"*64, (
            PageStructure(1, 100, 100, (block,), ()),
            PageStructure(2, 100, 100, (block,), ()),
        ), "parser", "1",
    )
    with pytest.raises(InvalidDocumentStructure, match="DUPLICATE_BLOCK_ID"):
        validate_structured_document(obs(), doc)
