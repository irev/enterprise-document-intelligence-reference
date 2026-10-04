"""Live PostgreSQL proof for invocation-time authorization revocation.

Enabled only when EDI_TEST_POSTGRES_DSN is supplied.
"""

import os

import pytest

from edi_reference.adapters.postgresql_control_plane import PostgreSqlProviderConfigurationSource
from edi_reference.application.planned_provider import invoke_planned_provider
from edi_reference.application.provider_config import ProviderConfigurationError
from edi_reference.domain.execution import Capability, DataEgress, ExecutionClass, ExecutionPolicy, PlannedStep, ProviderCapability
from edi_reference.domain.invocation import InvocationLimits, InvocationResult

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")

PROVIDER = ProviderCapability(
    "integration-local-ocr", "1", ExecutionClass.OCR,
    frozenset({Capability.TEXT_EXTRACTION}), DataEgress.NONE,
)
STEP = PlannedStep(
    Capability.TEXT_EXTRACTION, "integration-local-ocr", "1",
    ExecutionClass.OCR, "INTEGRATION_TEST",
)
POLICY = ExecutionPolicy("integration-local-only", "1", frozenset({ExecutionClass.OCR}), False)


class Invoker:
    def __init__(self):
        self.calls = 0

    def invoke(self, request, limits):
        self.calls += 1
        return InvocationResult(request.provider_id, request.provider_version, b"ok")


def connect():
    import psycopg
    return psycopg.connect(DSN)


def execute_sql(sql, params=()):
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)


def test_committed_authorization_revocation_blocks_stale_plan():
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM control_plane.provider_application_authorization WHERE provider_id = %s", (PROVIDER.provider_id,))
            cursor.execute("DELETE FROM control_plane.provider_tenant_authorization WHERE provider_id = %s", (PROVIDER.provider_id,))
            cursor.execute("DELETE FROM control_plane.provider_configuration WHERE provider_id = %s", (PROVIDER.provider_id,))
            cursor.execute("DELETE FROM control_plane.application WHERE tenant_id = %s", ("integration-tenant",))
            cursor.execute("DELETE FROM control_plane.tenant WHERE tenant_id = %s", ("integration-tenant",))
            cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES (%s)", ("integration-tenant",))
            cursor.execute("INSERT INTO control_plane.application (tenant_id, application_id) VALUES (%s, %s)", ("integration-tenant", "integration-app"))
            cursor.execute(
                """INSERT INTO control_plane.provider_configuration
                   (provider_id, provider_version, config_version, enabled, deployment_zone, engine_ref,
                    tenant_access_mode, application_access_mode)
                   VALUES (%s, %s, %s, true, %s, %s, 'ALLOWLIST', 'ALLOWLIST')""",
                (PROVIDER.provider_id, PROVIDER.provider_version, "cfg-1", "test", "fake"),
            )
            cursor.execute(
                "INSERT INTO control_plane.provider_tenant_authorization (provider_id, tenant_id) VALUES (%s, %s)",
                (PROVIDER.provider_id, "integration-tenant"),
            )
            cursor.execute(
                """INSERT INTO control_plane.provider_application_authorization
                   (provider_id, tenant_id, application_id) VALUES (%s, %s, %s)""",
                (PROVIDER.provider_id, "integration-tenant", "integration-app"),
            )

    source = PostgreSqlProviderConfigurationSource(connect)
    assert source.get(PROVIDER.provider_id).tenant_allowlist == frozenset({"integration-tenant"})

    # Simulate a plan that already exists, then commit revocation.
    execute_sql(
        "DELETE FROM control_plane.provider_application_authorization WHERE provider_id = %s",
        (PROVIDER.provider_id,),
    )

    invoker = Invoker()
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_NOT_ALLOWED_FOR_APPLICATION"):
        invoke_planned_provider(
            STEP, attempt_id="attempt-after-revoke", input_bytes=b"document",
            provider=PROVIDER, configurations=source,
            tenant_id="integration-tenant", application_id="integration-app",
            policy=POLICY, limits=InvocationLimits(5, 1024, 1024), invoker=invoker,
        )
    assert invoker.calls == 0



def test_application_authorization_does_not_leak_across_tenants():
    tenant_a = "integration-tenant-a"
    tenant_b = "integration-tenant-b"
    shared_app = "shared-app"

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM control_plane.provider_application_authorization WHERE provider_id = %s",
                (PROVIDER.provider_id,),
            )
            cursor.execute(
                "DELETE FROM control_plane.provider_tenant_authorization WHERE provider_id = %s",
                (PROVIDER.provider_id,),
            )
            cursor.execute(
                "DELETE FROM control_plane.provider_configuration WHERE provider_id = %s",
                (PROVIDER.provider_id,),
            )
            cursor.execute(
                "DELETE FROM control_plane.application WHERE tenant_id IN (%s, %s)",
                (tenant_a, tenant_b),
            )
            cursor.execute(
                "DELETE FROM control_plane.tenant WHERE tenant_id IN (%s, %s)",
                (tenant_a, tenant_b),
            )
            cursor.execute(
                "INSERT INTO control_plane.tenant (tenant_id) VALUES (%s), (%s)",
                (tenant_a, tenant_b),
            )
            cursor.execute(
                """INSERT INTO control_plane.application (tenant_id, application_id)
                   VALUES (%s, %s), (%s, %s)""",
                (tenant_a, shared_app, tenant_b, shared_app),
            )
            cursor.execute(
                """INSERT INTO control_plane.provider_configuration
                   (provider_id, provider_version, config_version, enabled, deployment_zone, engine_ref,
                    tenant_access_mode, application_access_mode)
                   VALUES (%s, %s, %s, true, %s, %s, 'UNRESTRICTED', 'ALLOWLIST')""",
                (PROVIDER.provider_id, PROVIDER.provider_version, "cfg-cross-tenant", "test", "fake"),
            )
            cursor.execute(
                """INSERT INTO control_plane.provider_application_authorization
                   (provider_id, tenant_id, application_id) VALUES (%s, %s, %s)""",
                (PROVIDER.provider_id, tenant_a, shared_app),
            )

    source = PostgreSqlProviderConfigurationSource(connect)
    config = source.get(PROVIDER.provider_id)
    assert config.application_allowlist == frozenset({(tenant_a, shared_app)})

    allowed_invoker = Invoker()
    invoke_planned_provider(
        STEP, attempt_id="attempt-tenant-a", input_bytes=b"document",
        provider=PROVIDER, configurations=source,
        tenant_id=tenant_a, application_id=shared_app,
        policy=POLICY, limits=InvocationLimits(5, 1024, 1024), invoker=allowed_invoker,
    )
    assert allowed_invoker.calls == 1

    denied_invoker = Invoker()
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_NOT_ALLOWED_FOR_APPLICATION"):
        invoke_planned_provider(
            STEP, attempt_id="attempt-tenant-b", input_bytes=b"document",
            provider=PROVIDER, configurations=source,
            tenant_id=tenant_b, application_id=shared_app,
            policy=POLICY, limits=InvocationLimits(5, 1024, 1024), invoker=denied_invoker,
        )
    assert denied_invoker.calls == 0
