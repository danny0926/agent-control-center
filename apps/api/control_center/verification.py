"""Owner-attested acceptance tied to a clean Git revision and immutable evidence hashes."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
import stat

from pydantic import BaseModel, Field

from .notifications import emit_event


class VerificationPolicyRequest(BaseModel):
    required_gates: list[str] = Field(min_length=1, max_length=20)


class CheckResult(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    passed: bool
    evidence_paths: list[str] = Field(min_length=1, max_length=20)


class VerificationRequest(BaseModel):
    node_id: str
    revision: str
    policy_id: str
    acceptance_results: list[CheckResult] = Field(min_length=1, max_length=100)
    gate_results: list[CheckResult] = Field(min_length=1, max_length=20)
    expires_at: datetime


def initialize_verification(c):
    c.execute("""CREATE TABLE IF NOT EXISTS verification_policies (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, node_id TEXT NOT NULL,
        scope_hash TEXT NOT NULL, gates_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS verification_records (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, node_id TEXT NOT NULL,
        revision TEXT NOT NULL, scope_hash TEXT NOT NULL, policy_id TEXT NOT NULL,
        checks_json TEXT NOT NULL, evidence_json TEXT NOT NULL, actor TEXT NOT NULL,
        created_at TEXT NOT NULL, expires_at TEXT NOT NULL, invalidated_at TEXT,
        invalidation_reason TEXT, UNIQUE(project_id,node_id,revision,scope_hash,policy_id,evidence_json))""")
    if "source_root" not in {row[1] for row in c.execute("PRAGMA table_info(verification_records)")}:
        c.execute("ALTER TABLE verification_records ADD COLUMN source_root TEXT")


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node.children)


def scope_hash(node):
    def content(n):
        return {"id": n.id, "title": n.title, "acceptance": n.acceptance_criteria,
                "children": [content(child) for child in n.children]}
    return hashlib.sha256(json.dumps(content(node), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def clean_revision(root: str) -> str:
    try:
        head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True, timeout=8).stdout.strip()
        status = subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=normal"],
                                capture_output=True, text=True, check=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError("無法核對已提交的 Git 版本；請先完成版本紀錄。") from None
    if status.strip():
        raise ValueError("工作目錄尚有未提交變更；請先提交待驗收版本。證據可放在已忽略的資料夾。")
    return head


def evidence_hash(root: str, relative: str) -> str:
    base = Path(root).resolve()
    supplied = Path(relative)
    if not relative or supplied.is_absolute() or ".." in supplied.parts or "\\" in relative or ":" in relative:
        raise ValueError("驗收證據必須是此專案內的相對檔案路徑。")
    if any(part.casefold() in {".git", ".codex", ".claude", ".ssh", ".aws", ".azure", ".openai"}
           or part.casefold().startswith(".env") for part in supplied.parts):
        raise ValueError("登入設定或 Git 內部資料不能作為驗收證據。")
    path = base
    for part in supplied.parts:
        path = path / part
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("驗收證據不能透過符號連結或 junction 讀取。")
    resolved = path.resolve()
    if base not in resolved.parents or not resolved.is_file():
        raise ValueError("驗收證據必須是此專案內的相對檔案路徑。")
    # Read a bounded regular file; do not let a growing file allocate unbounded memory.
    with resolved.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > 8 * 1024 * 1024:
            raise ValueError("單一證據檔案超過 8 MiB 或不是一般檔案；請提供有界的測試摘要。")
        data = stream.read(8 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    if len(data) > 8 * 1024 * 1024 or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("讀取期間證據已改變或超出大小限制。")
    return hashlib.sha256(data).hexdigest()


class VerificationService:
    def __init__(self, store):
        self.store = store

    def _project_node(self, project_id, node_id):
        project = self.store.get_project(project_id)
        if project is None:
            raise KeyError("找不到這個專案。")
        node = next((n for n in flatten(project.plan) if n.id == node_id), None)
        if node is None:
            raise KeyError("找不到這個成果項目。")
        return project, node

    def set_policy(self, project_id, node_id, request):
        gates = [v.strip() for v in request.required_gates]
        if any(not v or len(v) > 120 for v in gates) or len(gates) != len(set(gates)):
            raise ValueError("必要檢查名稱不可空白或重複。")
        with self.store._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            _, node = self._project_node(project_id, node_id)
            policy = {"id": str(uuid.uuid4()), "project_id": project_id, "node_id": node_id,
                      "scope_hash": scope_hash(node), "required_gates": gates,
                      "created_at": datetime.now(timezone.utc).isoformat()}
            c.execute("INSERT INTO verification_policies VALUES (?,?,?,?,?,?)",
                      (policy["id"], project_id, node_id, policy["scope_hash"], json.dumps(gates), policy["created_at"]))
            for row in c.execute("SELECT * FROM verification_records WHERE project_id=? AND node_id=? AND invalidated_at IS NULL",
                                 (project_id, node_id)).fetchall():
                self._invalidate(c, row, "驗收規則已變更。", policy["created_at"])
        return policy

    @staticmethod
    def _invalidate(c, row, reason, now):
        changed = c.execute("UPDATE verification_records SET invalidated_at=?,invalidation_reason=? WHERE id=? AND invalidated_at IS NULL",
                            (now, reason, row["id"])).rowcount
        if changed:
            emit_event(c, source_key=f"verification-invalidated:{row['id']}", event_type="work.verification_invalidated",
                       project_id=row["project_id"], entity_id=row["node_id"], identity={"record_id": row["id"]})

    def policy(self, project_id, node_id):
        with self.store._connect() as c:
            row = c.execute("SELECT * FROM verification_policies WHERE project_id=? AND node_id=? ORDER BY rowid DESC LIMIT 1",
                            (project_id, node_id)).fetchone()
        if row is None:
            return None
        return {**dict(row), "required_gates": json.loads(row["gates_json"])}

    def submit(self, project_id, request, actor="local-owner"):
        if actor != "local-owner":
            raise ValueError("驗收須由此部署的擁有者確認。")
        project, node = self._project_node(project_id, request.node_id)
        if project.plan_status != "confirmed" or not project.source_path or not node.acceptance_criteria:
            raise ValueError("需要已確認的計畫、本機來源及逐條驗收條件。")
        if node.children:
            raise ValueError("請先對最末層成果逐項驗收；上層完成需要另外核對所有子項。")
        policy = self.policy(project_id, node.id)
        current_scope = scope_hash(node)
        if not policy or policy["id"] != request.policy_id or policy["scope_hash"] != current_scope:
            raise ValueError("驗收規則已變更或尚未設定，請重新讀取。")
        if clean_revision(project.source_path) != request.revision:
            raise ValueError("驗收證據的版本與目前 Git 版本不一致。")
        now = datetime.now(timezone.utc)
        if request.expires_at.tzinfo is None or request.expires_at <= now:
            raise ValueError("證據有效期限必須是含時區的未來時間。")
        for expected, results in ((node.acceptance_criteria, request.acceptance_results),
                                  (policy["required_gates"], request.gate_results)):
            names = [result.name for result in results]
            if len(names) != len(set(names)) or set(names) != set(expected) or not all(result.passed for result in results):
                raise ValueError("所有必要驗收與檢查都必須逐條通過，且不可遺漏、重複或增加替代條件。")
        evidence_paths = {path for result in [*request.acceptance_results, *request.gate_results] for path in result.evidence_paths}
        if len(evidence_paths) > 40:
            raise ValueError("單次驗收最多使用 40 個不同證據檔案；請提供彙整摘要。")
        evidence = {path: evidence_hash(project.source_path, path) for path in sorted(evidence_paths)}
        # Recheck after reading files; concurrent source edits invalidate this submission.
        if clean_revision(project.source_path) != request.revision:
            raise ValueError("讀取證據期間版本已改變。")
        evidence_json = json.dumps(evidence, sort_keys=True)
        record_id = str(uuid.uuid4())
        with self.store._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            latest_project, latest_node = self._project_node(project_id, request.node_id)
            if (latest_project.plan_status != "confirmed" or latest_project.source_path != project.source_path
                    or scope_hash(latest_node) != current_scope):
                raise ValueError("讀取證據期間驗收範圍已變更。")
            row = c.execute("SELECT id FROM verification_policies WHERE project_id=? AND node_id=? ORDER BY rowid DESC LIMIT 1",
                            (project_id, node.id)).fetchone()
            if not row or row[0] != policy["id"]:
                raise ValueError("驗收規則已變更，請重新讀取。")
            if (clean_revision(project.source_path) != request.revision
                    or any(evidence_hash(project.source_path, path) != digest for path, digest in evidence.items())
                    or clean_revision(project.source_path) != request.revision):
                raise ValueError("提交期間版本或證據已變更。")
            now = datetime.now(timezone.utc)
            if request.expires_at <= now:
                raise ValueError("證據已超過有效期限。")
            c.execute("""INSERT OR IGNORE INTO verification_records
                (id,project_id,node_id,revision,scope_hash,policy_id,checks_json,evidence_json,actor,created_at,expires_at,source_root)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (record_id, project_id, node.id, request.revision, current_scope,
                policy["id"], request.model_dump_json(), evidence_json, actor, now.isoformat(), request.expires_at.isoformat(), str(Path(project.source_path).resolve())))
            row = c.execute("""SELECT id,invalidated_at,expires_at FROM verification_records
                WHERE project_id=? AND node_id=? AND revision=? AND scope_hash=? AND policy_id=? AND evidence_json=?""",
                (project_id, node.id, request.revision, current_scope, policy["id"], evidence_json)).fetchone()
            if row["invalidated_at"] or datetime.fromisoformat(row["expires_at"]) <= now:
                raise ValueError("相同證據的舊紀錄已失效；請更新證據或驗收規則後重新驗收。")
            record_id = row["id"]
            emit_event(c, source_key=f"verification:{record_id}", event_type="work.verified", project_id=project_id,
                       entity_id=node.id, identity={"record_id": record_id, "revision": request.revision, "scope_hash": current_scope})
        return {"id": record_id, "status": "verified", "source": "owner_attested", "revision": request.revision}

    def reconcile(self, project_id):
        with self.store._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            project = self.store.get_project(project_id)
            if not project:
                return
            nodes = {node.id: node for node in flatten(project.plan)}
            rows = c.execute("SELECT * FROM verification_records WHERE project_id=? AND invalidated_at IS NULL", (project_id,)).fetchall()
            if not rows:
                return
            try:
                revision = clean_revision(project.source_path or "") if project.source_path else None
            except ValueError:
                revision = None
            now = datetime.now(timezone.utc)
            for row in rows:
                reason = None
                node = nodes.get(row["node_id"])
                policy = c.execute("SELECT id FROM verification_policies WHERE project_id=? AND node_id=? ORDER BY rowid DESC LIMIT 1",
                                   (project_id, row["node_id"])).fetchone()
                if (project.plan_status != "confirmed" or not node or node.children
                        or scope_hash(node) != row["scope_hash"] or not policy or policy["id"] != row["policy_id"]):
                    reason = "驗收範圍或規則已改變。"
                elif not project.source_path or str(Path(project.source_path).resolve()) != row["source_root"]:
                    reason = "專案來源已變更或缺少原始來源綁定。"
                elif revision != row["revision"]:
                    reason = "版本已變更或工作目錄尚未提交。"
                else:
                    try:
                        expiry = datetime.fromisoformat(row["expires_at"])
                        if expiry.tzinfo is None or expiry <= now:
                            reason = "證據已超過有效期限或期限無效。"
                        elif any(evidence_hash(project.source_path, path) != digest for path, digest in json.loads(row["evidence_json"]).items()):
                            reason = "證據內容已變更。"
                    except (ValueError, OSError, TypeError):
                        reason = "無法再核對原始證據。"
                if reason:
                    self._invalidate(c, row, reason, now.isoformat())

    def list(self, project_id):
        if self.store.get_project(project_id) is None:
            raise KeyError("找不到這個專案。")
        self.reconcile(project_id)
        with self.store._connect() as c:
            rows = c.execute("SELECT * FROM verification_records WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
        return [{key: row[key] for key in ("id", "project_id", "node_id", "revision", "scope_hash", "policy_id", "actor",
                                          "created_at", "expires_at", "invalidated_at", "invalidation_reason")}
                | {"source": "owner_attested", "status": "invalidated" if row["invalidated_at"] else "verified",
                   "evidence": json.loads(row["evidence_json"])} for row in rows]
