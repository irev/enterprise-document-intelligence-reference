from edi_reference.adapters.postgresql_control_plane import PostgreSqlProviderConfigurationSource


class Cursor:
    def __init__(self):
        self.query = ""

    def execute(self, query, params):
        self.query = query

    def fetchone(self):
        if "provider_configuration" in self.query:
            return ("local-ocr", "cfg-2", False, "trusted-local", "paddle", None, None, "ALLOWLIST", "ALLOWLIST")
        return None

    def fetchall(self):
        if "provider_tenant_authorization" in self.query:
            return [("tenant-a",)]
        if "provider_application_authorization" in self.query:
            return [("tenant-a", "app-a")]
        return []

    def close(self):
        pass


class Connection:
    def __init__(self):
        self.closed = False

    def cursor(self):
        return Cursor()

    def close(self):
        self.closed = True


def test_postgresql_source_returns_current_configuration_and_authorization():
    connection = Connection()
    source = PostgreSqlProviderConfigurationSource(lambda: connection)
    result = source.get("local-ocr")
    assert result.provider_id == "local-ocr"
    assert result.config_version == "cfg-2"
    assert result.enabled is False
    assert result.tenant_allowlist == frozenset({"tenant-a"})
    assert result.application_allowlist == frozenset({("tenant-a", "app-a")})
    assert connection.closed


def test_postgresql_source_preserves_unrestricted_authorization():
    class UnrestrictedCursor(Cursor):
        def fetchone(self):
            if "provider_configuration" in self.query:
                return ("local-ocr", "cfg-3", True, "trusted-local", "paddle", None, None, "UNRESTRICTED", "UNRESTRICTED")
            return None

        def fetchall(self):
            return []

    class UnrestrictedConnection(Connection):
        def cursor(self):
            return UnrestrictedCursor()

    source = PostgreSqlProviderConfigurationSource(lambda: UnrestrictedConnection())
    result = source.get("local-ocr")
    assert result.tenant_allowlist is None
    assert result.application_allowlist is None
