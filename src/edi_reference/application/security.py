"""Security invariants for acquisition metadata."""

from urllib.parse import urlsplit

from edi_reference.domain.source import AcquisitionMethod, SourceReference


class UnsafeSourceReference(ValueError):
    pass


def validate_source_reference(source: SourceReference) -> None:
    """Reject dangerous reference shapes before an adapter performs I/O.

    Network adapters still must enforce DNS/IP/redirect policy at connection time.
    """
    if source.method is AcquisitionMethod.SIGNED_URL:
        if not source.resource_locator:
            raise UnsafeSourceReference("SOURCE_LOCATION_REQUIRED")
        parts = urlsplit(source.resource_locator)
        if parts.scheme.lower() != "https":
            raise UnsafeSourceReference("HTTPS_REQUIRED")
        if parts.username or parts.password:
            raise UnsafeSourceReference("EMBEDDED_CREDENTIALS_FORBIDDEN")
        if not parts.hostname:
            raise UnsafeSourceReference("SOURCE_HOST_REQUIRED")
        if parts.fragment:
            raise UnsafeSourceReference("URL_FRAGMENT_FORBIDDEN")

    if source.method is AcquisitionMethod.CONNECTOR:
        if not source.connector_id or not source.resource_locator:
            raise UnsafeSourceReference("CONNECTOR_AND_RESOURCE_REQUIRED")
        lowered = source.resource_locator.lower()
        if "://" in lowered or "@" in lowered:
            raise UnsafeSourceReference("CONNECTOR_RESOURCE_MUST_BE_OPAQUE")

    if source.method is AcquisitionMethod.UPLOAD:
        if source.connector_id or source.resource_locator:
            raise UnsafeSourceReference("UPLOAD_MUST_NOT_REFERENCE_REMOTE_SOURCE")
