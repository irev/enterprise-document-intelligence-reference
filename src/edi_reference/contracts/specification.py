"""Specification identity targeted by this reference implementation."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpecificationTarget:
    """Version identities required to interpret observable results."""

    specification_version: str
    canonical_schema_version: str
    policy_language_version: str


TARGET = SpecificationTarget(
    specification_version="0.9",
    canonical_schema_version="2.0",
    policy_language_version="1.0",
)
