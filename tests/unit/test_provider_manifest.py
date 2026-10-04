from edi_reference.application.provider_manifest import load_provider_manifest


def test_manifest_exposes_paddle_models() -> None:
    manifest = load_provider_manifest()

    paddle = manifest.providers["paddle-ocr"]

    assert paddle.runtime_family == "paddle"
    assert paddle.profiles == ("cpu", "nvidia")
    assert paddle.models == ("pp-ocrv6-medium", "pp-ocrv5-server", "pp-structure-v3")


def test_manifest_keeps_core_ml_optional() -> None:
    manifest = load_provider_manifest()

    assert all(not provider.required for provider in manifest.providers.values())
