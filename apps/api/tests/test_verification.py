import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from control_center import verification as v
from control_center.notifications import initialize_notifications


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


class FixtureStore:
    def __init__(self, root, db):
        self.path = db
        self.project = SimpleNamespace(id="p1", source_path=str(root), plan_status="confirmed", plan=[
            SimpleNamespace(id="leaf", title="成果", acceptance_criteria=["入口可用", "錯誤有說明"], children=[]),
        ])
        with self._connect() as c:
            initialize_notifications(c)
            v.initialize_verification(c)

    def _connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def get_project(self, project_id):
        return copy.deepcopy(self.project) if project_id == "p1" else None


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    (root / ".gitignore").write_text("reports/\n.env*\n.codex/\n.claude/\n", encoding="utf-8")
    (root / "app.txt").write_text("committed source", encoding="utf-8")
    git(root, "add", ".")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
    (root / "reports").mkdir()
    (root / "reports" / "result.txt").write_text("private report contents", encoding="utf-8")
    store = FixtureStore(root, tmp_path / "records.db")
    service = v.VerificationService(store)
    policy = service.set_policy("p1", "leaf", v.VerificationPolicyRequest(required_gates=["unit", "browser"]))
    def result(name):
        return v.CheckResult(name=name, passed=True, evidence_paths=["reports/result.txt"])
    request = v.VerificationRequest(node_id="leaf", revision=git(root, "rev-parse", "HEAD"), policy_id=policy["id"],
        acceptance_results=[result("入口可用"), result("錯誤有說明")], gate_results=[result("unit"), result("browser")],
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    return root, store, service, request


def count(store, table):
    with store._connect() as c:
        return c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_owner_attestation_replay_is_one_record_and_notification_without_contents(setup):
    root, store, service, request = setup
    first = service.submit("p1", request)
    assert service.submit("p1", request) == first
    assert first["source"] == "owner_attested"
    assert count(store, "verification_records") == count(store, "notifications") == 1
    records = service.list("p1")
    assert records[0]["invalidated_at"] is None
    assert records[0]["evidence"] == {"reports/result.txt": v.evidence_hash(str(root), "reports/result.txt")}
    serialized = json.dumps(records)
    assert "private report contents" not in serialized
    assert "checks_json" not in serialized and "source_root" not in serialized
    assert str(root) not in serialized


@pytest.mark.parametrize("change", ["no_policy", "no_criteria", "missing_acceptance", "missing_gate", "false_gate", "extra_gate", "duplicate", "wrong_revision", "dirty", "parent", "draft", "expired", "naive", "actor"])
def test_incomplete_or_invalid_attestation_cannot_verify(setup, change):
    root, store, service, request = setup
    if change == "no_policy":
        with store._connect() as c:
            c.execute("DELETE FROM verification_policies")
    elif change == "no_criteria":
        store.project.plan[0].acceptance_criteria = []
    elif change == "missing_acceptance":
        request.acceptance_results.pop()
    elif change == "missing_gate":
        request.gate_results.pop()
    elif change == "false_gate":
        request.gate_results[0].passed = False
    elif change == "extra_gate":
        request.gate_results.append(v.CheckResult(name="substitute", passed=True, evidence_paths=["reports/result.txt"]))
    elif change == "duplicate":
        request.acceptance_results[1] = request.acceptance_results[0]
    elif change == "wrong_revision":
        request.revision = "0" * 40
    elif change == "dirty":
        (root / "app.txt").write_text("uncommitted", encoding="utf-8")
    elif change == "parent":
        child = copy.deepcopy(store.project.plan[0])
        child.id = "child"
        store.project.plan[0].children = [child]
    elif change == "draft":
        store.project.plan_status = "draft"
    elif change == "expired":
        request.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif change == "naive":
        request.expires_at = datetime.now() + timedelta(hours=1)
    with pytest.raises(ValueError):
        service.submit("p1", request, actor="agent" if change == "actor" else "local-owner")
    assert count(store, "verification_records") == count(store, "notifications") == 0


def test_non_utc_aware_expiry_is_accepted(setup):
    _, _, service, request = setup
    request.expires_at = request.expires_at.astimezone(timezone(timedelta(hours=8)))
    assert service.submit("p1", request)["status"] == "verified"


@pytest.mark.parametrize("path", ["../outside", ".env", ".ENV.local", ".git/config", ".codex/session.json", ".claude/session.json", "reports/../../outside", "reports/file:secret", "reports\\result.txt"])
def test_secret_metadata_and_escaping_paths_are_rejected(setup, path):
    root, _, _, _ = setup
    with pytest.raises(ValueError):
        v.evidence_hash(str(root), path)


def test_absolute_path_and_symlink_are_rejected(setup):
    root, _, _, _ = setup
    with pytest.raises(ValueError):
        v.evidence_hash(str(root), str(root / "reports" / "result.txt"))
    link = root / "reports" / "link.txt"
    try:
        link.symlink_to(root / "reports" / "result.txt")
    except OSError:
        pytest.skip("OS未授予測試建立symlink的權限")
    with pytest.raises(ValueError):
        v.evidence_hash(str(root), "reports/link.txt")


def test_symlink_rejection_branch_without_os_privileges(setup, monkeypatch):
    root, _, _, _ = setup
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path.name == "result.txt" or original(path))
    with pytest.raises(ValueError, match="符號連結"):
        v.evidence_hash(str(root), "reports/result.txt")


def test_revision_change_during_final_evidence_read_rejected(setup, monkeypatch):
    root, store, service, request = setup
    original = v.evidence_hash
    reads = 0
    def racing(source, path):
        nonlocal reads
        reads += 1
        digest = original(source, path)
        if reads == 2:
            (root / "app.txt").write_text("changed while final evidence was read", encoding="utf-8")
        return digest
    monkeypatch.setattr(v, "evidence_hash", racing)
    with pytest.raises(ValueError):
        service.submit("p1", request)
    assert count(store, "verification_records") == 0


def test_large_evidence_is_rejected(setup):
    root, _, _, _ = setup
    with (root / "reports" / "large").open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(ValueError):
        v.evidence_hash(str(root), "reports/large")


@pytest.mark.parametrize("change", ["scope", "draft", "evidence", "missing", "dirty", "source", "expiry", "naive_expiry"])
def test_record_invalidates_and_emits_only_one_correction(setup, change):
    root, store, service, request = setup
    service.submit("p1", request)
    if change == "scope":
        store.project.plan[0].acceptance_criteria.append("新增條件")
    elif change == "draft":
        store.project.plan_status = "draft"
    elif change == "evidence":
        (root / "reports" / "result.txt").write_text("different report", encoding="utf-8")
    elif change == "missing":
        (root / "reports" / "result.txt").unlink()
    elif change == "dirty":
        (root / "app.txt").write_text("new changes", encoding="utf-8")
    elif change == "source":
        store.project.source_path = None
    else:
        expiry = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat() if change == "expiry" else "2026-01-01T01:00:00"
        with store._connect() as c:
            c.execute("UPDATE verification_records SET expires_at=?", (expiry,))
    assert service.list("p1")[0]["invalidated_at"] is not None
    service.reconcile("p1")
    assert count(store, "domain_events") == count(store, "notifications") == 2


def test_new_expiry_cannot_revive_expired_duplicate(setup):
    _, store, service, request = setup
    service.submit("p1", request)
    with store._connect() as c:
        c.execute("UPDATE verification_records SET expires_at=?", ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),))
    request.expires_at += timedelta(days=1)
    with pytest.raises(ValueError):
        service.submit("p1", request)
    assert count(store, "domain_events") == 1


def test_policy_replacement_invalidates_once_and_allows_new_attestation(setup):
    _, store, service, request = setup
    old = service.submit("p1", request)
    policy = service.set_policy("p1", "leaf", v.VerificationPolicyRequest(required_gates=["unit", "browser"]))
    assert service.list("p1")[0]["invalidated_at"] is not None
    request.policy_id = policy["id"]
    new = service.submit("p1", request)
    assert new["id"] != old["id"]
    assert service.submit("p1", request) == new
    assert count(store, "domain_events") == count(store, "notifications") == 3


def test_file_metadata_only_change_does_not_change_evidence(setup):
    root, _, service, request = setup
    service.submit("p1", request)
    (root / "reports" / "result.txt").touch()
    assert service.list("p1")[0]["invalidated_at"] is None


def test_legacy_record_without_source_binding_is_not_silently_trusted(setup):
    _, store, service, request = setup
    service.submit("p1", request)
    with store._connect() as c:
        c.execute("UPDATE verification_records SET source_root=NULL")
        v.initialize_verification(c)
    assert service.list("p1")[0]["invalidated_at"] is not None


def test_evidence_collection_is_bounded_before_reading(setup):
    _, _, service, request = setup
    request.acceptance_results[0].evidence_paths = [f"reports/{n}.txt" for n in range(41)]
    with pytest.raises(ValueError, match="40"):
        service.submit("p1", request)


def test_scope_change_during_evidence_read_rejected(setup, monkeypatch):
    _, store, service, request = setup
    original = v.evidence_hash
    def racing(root, path):
        digest = original(root, path)
        store.project.plan[0].title = "scope changed during read"
        return digest
    monkeypatch.setattr(v, "evidence_hash", racing)
    with pytest.raises(ValueError):
        service.submit("p1", request)
    assert count(store, "verification_records") == 0


def test_policy_change_during_evidence_read_rejected(setup, monkeypatch):
    _, store, service, request = setup
    original = v.evidence_hash
    changed = False
    def racing(root, path):
        nonlocal changed
        digest = original(root, path)
        if not changed:
            changed = True
            service.set_policy("p1", "leaf", v.VerificationPolicyRequest(required_gates=["additional"]))
        return digest
    monkeypatch.setattr(v, "evidence_hash", racing)
    with pytest.raises(ValueError):
        service.submit("p1", request)
    assert count(store, "verification_records") == 0


@pytest.mark.parametrize("operation", ["submit", "invalidate", "policy"])
def test_event_failure_rolls_back_domain_mutation(setup, monkeypatch, operation):
    root, store, service, request = setup
    if operation != "submit":
        service.submit("p1", request)
    original = v.emit_event
    def failed(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated outbox failure")
    monkeypatch.setattr(v, "emit_event", failed)
    with pytest.raises(RuntimeError):
        if operation == "submit":
            service.submit("p1", request)
        elif operation == "invalidate":
            (root / "reports" / "result.txt").write_text("changed", encoding="utf-8")
            service.reconcile("p1")
        else:
            service.set_policy("p1", "leaf", v.VerificationPolicyRequest(required_gates=["new gate"]))
    assert count(store, "domain_events") == (0 if operation == "submit" else 1)
    assert count(store, "verification_policies") == 1
    with store._connect() as c:
        rows = c.execute("SELECT * FROM verification_records").fetchall()
    assert len(rows) == (0 if operation == "submit" else 1)
    assert all(row["invalidated_at"] is None for row in rows)
