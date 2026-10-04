from edi_reference.application.classification import ClassificationPolicy, RawClassification, classify_document
from edi_reference.domain.classification import ClassificationCandidate, UNKNOWN_DOCUMENT_TYPE
from edi_reference.domain.document_structure import BoundingBox, PageStructure, StructuredDocument, TextBlock
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference


DOC = StructuredDocument(
    "obs-1", "a"*64,
    (PageStructure(1, 100, 100, (TextBlock("b1", "Invoice INV-001", BoundingBox(.1,.1,.5,.2), 0),), ()),),
    "layout", "1",
)
EVIDENCE = (EvidenceReference("obs-1", "a"*64, 1, EvidenceKind.TEXT_BLOCK, block_id="b1", text_quote="Invoice"),)
POLICY = ClassificationPolicy(.80, .10)


class Classifier:
    model_id = "synthetic-classifier"
    model_version = "1"
    taxonomy_version = "1"
    def __init__(self, candidates):
        self.candidates = candidates
    def classify(self, document):
        return RawClassification(tuple(self.candidates), EVIDENCE)


def test_high_confidence_separated_candidate_is_accepted():
    result = classify_document(DOC, classifier=Classifier([
        ClassificationCandidate("INVOICE", .94),
        ClassificationCandidate("PURCHASE_ORDER", .20),
    ]), policy=POLICY)
    assert result.document_type == "INVOICE"
    assert result.model_version == "1"
    assert result.evidence == EVIDENCE


def test_low_confidence_abstains_to_unknown():
    result = classify_document(DOC, classifier=Classifier([
        ClassificationCandidate("INVOICE", .70),
    ]), policy=POLICY)
    assert result.document_type == UNKNOWN_DOCUMENT_TYPE


def test_ambiguous_top_candidates_abstain_to_unknown():
    result = classify_document(DOC, classifier=Classifier([
        ClassificationCandidate("INVOICE", .91),
        ClassificationCandidate("PURCHASE_ORDER", .86),
    ]), policy=POLICY)
    assert result.document_type == UNKNOWN_DOCUMENT_TYPE


def test_empty_prediction_abstains_to_unknown():
    result = classify_document(DOC, classifier=Classifier([]), policy=POLICY)
    assert result.document_type == UNKNOWN_DOCUMENT_TYPE
