import pytest

from edi_reference.application.security import UnsafeSourceReference, validate_source_reference
from edi_reference.domain.source import AcquisitionMethod, SourceReference


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid/document.pdf",
        "https://user:secret@example.invalid/document.pdf",
        "https://example.invalid/document.pdf#fragment",
    ],
)
def test_signed_url_rejects_unsafe_reference_shapes(url: str) -> None:
    with pytest.raises(UnsafeSourceReference):
        validate_source_reference(
            SourceReference(method=AcquisitionMethod.SIGNED_URL, resource_locator=url)
        )


def test_connector_resource_cannot_smuggle_endpoint_or_credentials() -> None:
    with pytest.raises(UnsafeSourceReference):
        validate_source_reference(
            SourceReference(
                method=AcquisitionMethod.CONNECTOR,
                connector_id="connector-1",
                resource_locator="sftp://user:secret@host/file.pdf",
            )
        )


def test_upload_cannot_select_remote_resource() -> None:
    with pytest.raises(UnsafeSourceReference):
        validate_source_reference(
            SourceReference(
                method=AcquisitionMethod.UPLOAD,
                resource_locator="https://example.invalid/file.pdf",
            )
        )


def test_safe_signed_url_shape_is_accepted() -> None:
    validate_source_reference(
        SourceReference(
            method=AcquisitionMethod.SIGNED_URL,
            resource_locator="https://files.example.invalid/document.pdf?token=opaque",
        )
    )
