import json

import pytest

from edi_reference.application.panel_audit import AuditLog, verify_chain
from edi_reference.application.panel_auth import LoginThrottle, Role, SessionManager, UserStore
from edi_reference.application.panel_config import ConfigStore

GOOD = "synthetic-Pass-123"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_passwords_are_hashed_and_verified(tmp_path):
    store = UserStore(tmp_path / "users.json", iterations=1000)
    store.upsert("admin", GOOD, Role.ADMIN)

    raw = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert GOOD not in raw
    assert store.verify("admin", GOOD).role is Role.ADMIN
    assert store.verify("admin", "wrong-Pass-123") is None
    assert store.verify("nobody", GOOD) is None


def test_user_rules_weak_password_name_and_last_admin(tmp_path):
    store = UserStore(tmp_path / "users.json", iterations=1000)
    with pytest.raises(ValueError, match="PASSWORD_TOO_WEAK"):
        store.upsert("admin", "short", Role.ADMIN)
    with pytest.raises(ValueError, match="INVALID_USERNAME"):
        store.upsert("Bad Name", GOOD, Role.ADMIN)
    with pytest.raises(ValueError, match="AT_LEAST_ONE_ACTIVE_ADMIN_REQUIRED"):
        store.upsert("viewer", GOOD, Role.VIEWER)
    store.upsert("admin", GOOD, Role.ADMIN)
    with pytest.raises(ValueError, match="AT_LEAST_ONE_ACTIVE_ADMIN_REQUIRED"):
        store.upsert("admin", None, disabled=True)
    store.upsert("op", GOOD, Role.OPERATOR)
    store.upsert("op", None, disabled=True)
    assert store.verify("op", GOOD) is None


def test_sessions_expire_on_idle_and_absolute_limits(tmp_path):
    store = UserStore(tmp_path / "users.json", iterations=1000)
    user = store.upsert("admin", GOOD, Role.ADMIN)
    clock = Clock()
    sessions = SessionManager(idle_seconds=10, absolute_seconds=25, clock=clock)
    session = sessions.create(user)

    clock.now += 9
    assert sessions.get(session.token) is session
    clock.now += 9
    assert sessions.get(session.token) is session
    clock.now += 9  # absolute limit reached even though it was used recently
    assert sessions.get(session.token) is None
    other = sessions.create(user)
    clock.now += 11
    assert sessions.get(other.token) is None
    assert sessions.get(None) is None


def test_throttle_locks_after_repeated_failures():
    clock = Clock()
    throttle = LoginThrottle(max_failures=3, window_seconds=60, lock_seconds=100, clock=clock)
    for _ in range(3):
        throttle.failure("user:a", "ip:1")
    assert throttle.blocked("user:a")
    assert throttle.blocked("ip:1")
    clock.now += 101
    assert not throttle.blocked("user:a", "ip:1")


def test_audit_chain_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.record("admin", "auth.login")
    log.record("admin", "config.save", target="pipeline@2")
    assert verify_chain(path) == (True, None)
    last = log.tail(1)[0]["hash"]
    assert AuditLog(path).record("op", "document.upload")["prev"] == last  # chain survives restart

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["actor"] = "intruder"
    lines[1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert verify_chain(path) == (False, 2)


def test_audit_refuses_secret_details(tmp_path):
    with pytest.raises(ValueError, match="AUDIT_DETAIL_FORBIDDEN"):
        AuditLog(tmp_path / "a.jsonl").record("admin", "user.save", password="x")


PIPELINE = {"classification_mode": "rules", "max_pages": 3,
            "llm": {"host": "127.0.0.1", "port": 12340, "model": "synthetic-model"},
            "ocr": {"det_name": "d", "det_dir": "/m/d", "rec_name": "r", "rec_dir": "/m/r"}}


def test_config_versions_are_immutable_and_activation_rolls_back(tmp_path):
    store = ConfigStore(tmp_path)
    v1 = store.save("pipeline", PIPELINE, author="admin", comment="first")
    v2 = store.save("pipeline", dict(PIPELINE, max_pages=5), author="admin", comment="more pages")

    assert (v1, v2) == (1, 2)
    assert store.active("pipeline")["max_pages"] == 5
    store.activate("pipeline", 1)
    assert store.active("pipeline")["max_pages"] == 3
    assert store.get("pipeline", 2)["content"]["max_pages"] == 5
    assert [v["comment"] for v in store.versions("pipeline")] == ["first", "more pages"]
    with pytest.raises(LookupError):
        store.activate("pipeline", 9)


@pytest.mark.parametrize(("kind", "content", "code"), [
    ("pipeline", dict(PIPELINE, llm={"host": "10.0.0.2", "port": 1, "model": "m"}), "LLM_ENDPOINT_MUST_BE_LOOPBACK"),
    ("pipeline", dict(PIPELINE, classification_mode="magic"), "INVALID_CLASSIFICATION_MODE"),
    ("pipeline", dict(PIPELINE, max_pages=0), "INVALID_MAX_PAGES"),
    ("extraction_schema", {"schema_id": "s", "version": "1", "fields": [{"field_name": "Bad Name", "value_type": "string"}]},
     "INVALID_FIELD_NAME"),
    ("title_rules", {"profile_id": "p", "version": "1", "taxonomy_version": "t", "rules": [{"pattern": "(", "document_type": "X"}]},
     "INVALID_TITLE_RULE_PATTERN"),
])
def test_config_is_validated_before_storage(tmp_path, kind, content, code):
    store = ConfigStore(tmp_path)
    with pytest.raises(ValueError, match=code):
        store.save(kind, content, author="admin")
    assert store.versions(kind) == []
