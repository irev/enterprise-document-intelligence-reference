import os

import pytest

from edi_reference.adapters.postgresql_processing_profile import PostgreSqlProcessingProfileSource
from edi_reference.domain.execution import Capability, ExecutionClass

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


def cleanup(cursor):
    cursor.execute(
        "DELETE FROM control_plane.processing_profile_binding WHERE tenant_id = 'profile-tenant'"
    )
    cursor.execute(
        "DELETE FROM control_plane.processing_profile_version WHERE profile_id LIKE 'profile-integration-%'"
    )
    cursor.execute(
        "DELETE FROM control_plane.execution_policy_version WHERE policy_id LIKE 'policy-integration-%'"
    )
    cursor.execute(
        "DELETE FROM control_plane.application WHERE tenant_id = 'profile-tenant'"
    )
    cursor.execute(
        "DELETE FROM control_plane.tenant WHERE tenant_id = 'profile-tenant'"
    )


def test_durable_application_profile_overrides_tenant_default():
    with connect() as connection:
        with connection.cursor() as cursor:
            cleanup(cursor)
            cursor.execute(
                "INSERT INTO control_plane.tenant (tenant_id) VALUES ('profile-tenant')"
            )
            cursor.execute(
                """INSERT INTO control_plane.application (tenant_id, application_id)
                   VALUES ('profile-tenant', 'profile-app')"""
            )
            for suffix in ("default", "app"):
                cursor.execute(
                    """INSERT INTO control_plane.execution_policy_version
                       (policy_id, policy_version, policy_document)
                       VALUES (%s, '1', %s::jsonb)""",
                    (
                        f"policy-integration-{suffix}",
                        """{"allowed_execution_classes":["LOCAL_MODEL"],
                            "allow_external_egress":false,
                            "allow_fallback":false,
                            "capability_policies":[
                              {"capability":"CLASSIFICATION","preference":["LOCAL_MODEL"]}
                            ]}""",
                    ),
                )
                cursor.execute(
                    """INSERT INTO control_plane.processing_profile_version
                       (profile_id, profile_version, policy_id, policy_version)
                       VALUES (%s, '1', %s, '1')""",
                    (
                        f"profile-integration-{suffix}",
                        f"policy-integration-{suffix}",
                    ),
                )
            cursor.execute(
                """INSERT INTO control_plane.processing_profile_binding
                   (tenant_id, application_id, profile_id, profile_version)
                   VALUES
                     ('profile-tenant', NULL, 'profile-integration-default', '1'),
                     ('profile-tenant', 'profile-app', 'profile-integration-app', '1')"""
            )

    registry = PostgreSqlProcessingProfileSource(connect).load_registry()
    selected = registry.resolve(
        tenant_id="profile-tenant", application_id="profile-app"
    )
    assert selected.profile_id == "profile-integration-app"
    assert selected.execution_policy.policy_id == "policy-integration-app"
    assert selected.execution_policy.allowed_execution_classes == frozenset(
        {ExecutionClass.LOCAL_MODEL}
    )
    assert selected.execution_policy.capability_policies[0].capability is Capability.CLASSIFICATION


def test_database_rejects_duplicate_tenant_default_binding():
    with connect() as connection:
        with connection.cursor() as cursor:
            cleanup(cursor)
            cursor.execute(
                "INSERT INTO control_plane.tenant (tenant_id) VALUES ('profile-tenant')"
            )
            cursor.execute(
                """INSERT INTO control_plane.execution_policy_version
                   (policy_id, policy_version, policy_document)
                   VALUES ('policy-integration-default', '1',
                           '{"allowed_execution_classes":["LOCAL_MODEL"],
                             "allow_external_egress":false}'::jsonb)"""
            )
            cursor.execute(
                """INSERT INTO control_plane.processing_profile_version
                   (profile_id, profile_version, policy_id, policy_version)
                   VALUES ('profile-integration-default', '1',
                           'policy-integration-default', '1')"""
            )
            cursor.execute(
                """INSERT INTO control_plane.processing_profile_binding
                   (tenant_id, application_id, profile_id, profile_version)
                   VALUES ('profile-tenant', NULL, 'profile-integration-default', '1')"""
            )
            with pytest.raises(Exception):
                cursor.execute(
                    """INSERT INTO control_plane.processing_profile_binding
                       (tenant_id, application_id, profile_id, profile_version)
                       VALUES ('profile-tenant', NULL, 'profile-integration-default', '1')"""
                )
