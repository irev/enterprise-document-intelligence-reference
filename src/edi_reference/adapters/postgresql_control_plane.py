"""PostgreSQL-backed current provider configuration source.

The adapter uses Python DB-API compatible connections so domain/application code
does not depend on a PostgreSQL driver or ORM.
"""

from collections.abc import Callable
from typing import Any

from edi_reference.application.provider_config import ProviderConfigurationSource
from edi_reference.domain.provider_config import ProviderConfiguration


class PostgreSqlProviderConfigurationSource(ProviderConfigurationSource):
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def get(self, provider_id: str) -> ProviderConfiguration | None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    SELECT provider_id, config_version, enabled, deployment_zone,
                           engine_ref, secret_ref, endpoint_ref,
                           tenant_access_mode, application_access_mode
                    FROM control_plane.provider_configuration
                    WHERE provider_id = %s
                    """,
                    (provider_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                cursor.execute(
                    """
                    SELECT tenant_id
                    FROM control_plane.provider_tenant_authorization
                    WHERE provider_id = %s AND authorized = true
                    ORDER BY tenant_id
                    """,
                    (provider_id,),
                )
                tenant_rows = frozenset(item[0] for item in cursor.fetchall())
                tenant_allowlist = None if row[7] == "UNRESTRICTED" else tenant_rows

                cursor.execute(
                    """
                    SELECT tenant_id, application_id
                    FROM control_plane.provider_application_authorization
                    WHERE provider_id = %s AND authorized = true
                    ORDER BY tenant_id, application_id
                    """,
                    (provider_id,),
                )
                application_rows = frozenset((item[0], item[1]) for item in cursor.fetchall())
                application_allowlist = None if row[8] == "UNRESTRICTED" else application_rows

                return ProviderConfiguration(
                    provider_id=row[0],
                    config_version=row[1],
                    enabled=row[2],
                    deployment_zone=row[3],
                    engine_ref=row[4],
                    secret_ref=row[5],
                    endpoint_ref=row[6],
                    tenant_allowlist=tenant_allowlist,
                    application_allowlist=application_allowlist,
                )
            finally:
                cursor.close()
        finally:
            connection.close()
