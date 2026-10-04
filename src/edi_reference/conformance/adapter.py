"""Boundary between portable conformance vectors and implementation behavior."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from edi_reference.domain.models import Capability, ObservableResult


class ConformanceAdapter(ABC):
    """Maps abstract specification inputs to observable implementation results."""

    @property
    @abstractmethod
    def capabilities(self) -> frozenset[Capability]:
        """Return capabilities this implementation explicitly claims."""

    @abstractmethod
    def execute(
        self,
        capability: Capability,
        vector_input: Mapping[str, Any],
    ) -> ObservableResult:
        """Execute one abstract conformance input.

        RI-0 defines the boundary only. Concrete behavior is introduced by
        later implementation milestones and MUST remain provider-neutral here.
        """
