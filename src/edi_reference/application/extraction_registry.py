"""Field catalog and per-category extraction schemas (RI-6.0 phase D).

One versioned configuration package holds:
- a reusable **field catalog** (stable id, value type, label, meaning);
- **category schemas** that reference catalog fields per document type;
- a **common schema** and explicit policies for `UNKNOWN` and for categories
  without their own schema (use the common schema, or extract nothing);
- the ordered **normalizer chain** per value type.

The package is activated as a whole, so a worker never sees a new category with
an old schema. The schema actually used is reported in result provenance;
nothing silently falls back to another category's schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edi_reference.domain.classification import UNKNOWN_DOCUMENT_TYPE
from edi_reference.domain.field_schema import ExtractionSchema, FieldDefinition

FIELD_ID = re.compile(r"[a-z][a-z0-9_]{0,63}")
CATEGORY_ID = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
SCHEMA_ID = re.compile(r"[a-z][a-z0-9-]{0,63}")
VALUE_TYPES = ("string", "date", "money", "identifier", "tax_id", "number")
POLICIES = ("COMMON", "NONE")
KNOWN_NORMALIZERS = (
    "date.iso-8601@1", "date.textual.id-en@1", "date.numeric.unambiguous@1", "date.numeric.day-first@1",
    "money.id-ID.IDR@1", "money.idr.multi-format@1", "identifier.trimmed@1", "tax_id.npwp@1",
)
_NORMALIZER_TYPE = {"date": "date", "money": "money", "identifier": "identifier", "tax_id": "tax_id"}


@dataclass(frozen=True, slots=True)
class FieldSpec:
    field_id: str
    value_type: str
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class SchemaSelection:
    """What the extractor runs for one document type."""

    schema: ExtractionSchema | None
    descriptions: dict[str, str]
    source: str  # CATEGORY | COMMON | NONE

    @property
    def reference(self) -> dict | None:
        return None if self.schema is None else {"id": self.schema.schema_id, "version": self.schema.version}


@dataclass(frozen=True, slots=True)
class ExtractionRegistry:
    registry_id: str
    version: str
    fields: dict[str, FieldSpec]
    common: ExtractionSchema
    categories: dict[str, ExtractionSchema]
    unknown_policy: str
    missing_category_policy: str
    normalizers: dict[str, tuple[tuple[str, str], ...]]

    def select(self, document_type: str) -> SchemaSelection:
        if document_type == UNKNOWN_DOCUMENT_TYPE:
            policy, schema, source = self.unknown_policy, self.common, "COMMON"
        elif document_type in self.categories:
            return self._selection(self.categories[document_type], "CATEGORY")
        else:
            policy, schema, source = self.missing_category_policy, self.common, "COMMON"
        if policy == "NONE":
            return SchemaSelection(None, {}, "NONE")
        return self._selection(schema, source)

    def _selection(self, schema: ExtractionSchema, source: str) -> SchemaSelection:
        return SchemaSelection(schema, {f.field_name: self.fields[f.field_name].description for f in schema.fields}, source)

    def normalizer_chain(self, value_type: str) -> tuple[tuple[str, str], ...]:
        return self.normalizers.get(value_type, ())


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("INVALID_REGISTRY_TEXT")
    return value


def _schema(raw: object, fields: dict[str, FieldSpec]) -> ExtractionSchema:
    if not isinstance(raw, dict) or not SCHEMA_ID.fullmatch(str(raw.get("schema_id", ""))):
        raise ValueError("INVALID_CATEGORY_SCHEMA")
    refs = raw.get("fields")
    if not isinstance(refs, list) or not 1 <= len(refs) <= 50 or len(set(refs)) != len(refs):
        raise ValueError("INVALID_CATEGORY_SCHEMA_FIELDS")
    unknown = [ref for ref in refs if ref not in fields]
    if unknown:
        raise ValueError("UNKNOWN_FIELD_REFERENCE:" + ",".join(map(str, unknown))[:200])
    version = str(raw.get("version", ""))
    if not re.fullmatch(r"[0-9]{1,6}", version):
        raise ValueError("INVALID_CATEGORY_SCHEMA_VERSION")
    return ExtractionSchema(raw["schema_id"], version, tuple(FieldDefinition(ref, fields[ref].value_type) for ref in refs))


def registry_from_dict(raw: object) -> ExtractionRegistry:
    if not isinstance(raw, dict):
        raise ValueError("INVALID_EXTRACTION_REGISTRY")
    catalog = raw.get("fields")
    if not isinstance(catalog, dict) or not 1 <= len(catalog) <= 200:
        raise ValueError("INVALID_FIELD_CATALOG")
    fields: dict[str, FieldSpec] = {}
    for field_id, spec in catalog.items():
        if not FIELD_ID.fullmatch(str(field_id)) or not isinstance(spec, dict):
            raise ValueError("INVALID_FIELD_ID")
        if spec.get("value_type") not in VALUE_TYPES:
            raise ValueError("INVALID_FIELD_VALUE_TYPE")
        description = _text(spec.get("description", ""), 300)
        if not description.strip():
            # The description is what tells the model which printed value is meant.
            raise ValueError("FIELD_DESCRIPTION_REQUIRED")
        fields[field_id] = FieldSpec(field_id, spec["value_type"], _text(spec.get("label", field_id), 100), description)
    categories_raw = raw.get("categories", {})
    if not isinstance(categories_raw, dict) or len(categories_raw) > 100:
        raise ValueError("INVALID_CATEGORIES")
    categories = {}
    for category, schema in categories_raw.items():
        if not CATEGORY_ID.fullmatch(str(category)) or category == UNKNOWN_DOCUMENT_TYPE:
            raise ValueError("INVALID_CATEGORY_ID")
        categories[category] = _schema(schema, fields)
    schema_ids = [s.schema_id for s in categories.values()]
    if len(schema_ids) != len(set(schema_ids)):
        raise ValueError("DUPLICATE_SCHEMA_ID")
    policies = (raw.get("unknown_policy"), raw.get("missing_category_policy"))
    if any(policy not in POLICIES for policy in policies):
        raise ValueError("INVALID_SCHEMA_POLICY")
    chains_raw = raw.get("normalizers", {})
    if not isinstance(chains_raw, dict):
        raise ValueError("INVALID_NORMALIZER_CHAINS")
    chains: dict[str, tuple[tuple[str, str], ...]] = {}
    for value_type, chain in chains_raw.items():
        if value_type not in _NORMALIZER_TYPE or not isinstance(chain, list) or not 1 <= len(chain) <= 5:
            raise ValueError("INVALID_NORMALIZER_CHAIN")
        steps = []
        for item in chain:
            if item not in KNOWN_NORMALIZERS or not str(item).split(".", 1)[0] == _NORMALIZER_TYPE[value_type]:
                raise ValueError(f"UNKNOWN_NORMALIZER:{str(item)[:80]}")
            name, version = str(item).rsplit("@", 1)
            steps.append((name, version))
        chains[value_type] = tuple(steps)
    if not re.fullmatch(r"[0-9]{1,6}", str(raw.get("version", ""))):
        raise ValueError("INVALID_REGISTRY_VERSION")
    return ExtractionRegistry(
        registry_id=_text(raw.get("registry_id", ""), 100) or "registry",
        version=str(raw["version"]), fields=fields, common=_schema(raw.get("common_schema"), fields),
        categories=categories, unknown_policy=str(policies[0]), missing_category_policy=str(policies[1]), normalizers=chains,
    )
