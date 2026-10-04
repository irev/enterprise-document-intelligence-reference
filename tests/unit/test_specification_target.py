from edi_reference.contracts.specification import TARGET


def test_reference_targets_v09_and_canonical_v2() -> None:
    assert TARGET.specification_version == "0.9"
    assert TARGET.canonical_schema_version == "2.0"
    assert TARGET.policy_language_version == "1.0"
