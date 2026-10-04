"""PostgreSQL-backed processing-profile control-plane source."""

from collections.abc import Callable
from typing import Any

from edi_reference.application.processing_profile import ProcessingProfileRegistry
from edi_reference.domain.execution import (
    Capability,
    CapabilityExecutionPolicy,
    ExecutionClass,
    ExecutionPolicy,
)
from edi_reference.domain.processing_profile import ProcessingProfile, ProcessingProfileBinding


class PostgreSqlProcessingProfileSource:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def load_registry(self) -> ProcessingProfileRegistry:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT p.profile_id, p.profile_version, p.policy_id,
                              p.policy_version, e.policy_document
                       FROM control_plane.processing_profile_version p
                       JOIN control_plane.execution_policy_version e
                         ON e.policy_id = p.policy_id
                        AND e.policy_version = p.policy_version
                       ORDER BY p.profile_id, p.profile_version"""
                )
                profiles = tuple(self._map_profile(row) for row in cursor.fetchall())

                cursor.execute(
                    """SELECT tenant_id, application_id, profile_id, profile_version
                       FROM control_plane.processing_profile_binding
                       ORDER BY tenant_id, application_id NULLS FIRST"""
                )
                bindings = tuple(
                    ProcessingProfileBinding(row[0], row[1], row[2], row[3])
                    for row in cursor.fetchall()
                )
        return ProcessingProfileRegistry(profiles, bindings)

    @staticmethod
    def _map_profile(row) -> ProcessingProfile:
        document = row[4]
        try:
            allowed = frozenset(
                ExecutionClass(value) for value in document["allowed_execution_classes"]
            )
            capability_policies = tuple(
                CapabilityExecutionPolicy(
                    Capability(item["capability"]),
                    tuple(ExecutionClass(value) for value in item["preference"]),
                )
                for item in document.get("capability_policies", ())
            )
            policy = ExecutionPolicy(
                policy_id=row[2],
                policy_version=row[3],
                allowed_execution_classes=allowed,
                allow_external_egress=document["allow_external_egress"],
                allow_fallback=document.get("allow_fallback", False),
                capability_policies=capability_policies,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("INVALID_EXECUTION_POLICY_DOCUMENT") from exc
        return ProcessingProfile(row[0], row[1], policy)
