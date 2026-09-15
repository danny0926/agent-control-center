from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
from httpx import BasicAuth

from control_center.main import app, store
from control_center.store import Store


client = TestClient(app)


def test_remote_login_protects_every_route(monkeypatch) -> None:
    monkeypatch.setenv("CONTROL_CENTER_USER", "owner")
    monkeypatch.setenv("CONTROL_CENTER_PASSWORD", "secret")

    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", auth=("owner", "wrong")).status_code == 401
    assert client.get("/api/health", auth=("owner", "secret")).status_code == 200


def test_agent_request_is_remembered_across_store_instances(tmp_path: Path) -> None:
    database = tmp_path / "agent-requests.db"
    first = Store(database)
    first.remember_agent_request("project-1", "wN:p1", "請完成最近的任務。", "control_center_sent")

    reopened = Store(database)

    assert reopened.latest_agent_request("project-1", "wN:p1") == (
        "請完成最近的任務。",
        "control_center_sent",
    )


def test_import_preview_then_confirm(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CONTROL_CENTER_USER", "test-owner")
    monkeypatch.setenv("CONTROL_CENTER_PASSWORD", "test-password")
    monkeypatch.setattr(client, "auth", BasicAuth("test-owner", "test-password"))
    database = tmp_path / "test.db"
    monkeypatch.setattr(store, "path", database)
    store._previews.clear()
    store._initialize()
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)
    (tmp_path / "README.md").write_text(
        "# Helpful Project\n\n這是一個讓使用者快速理解複雜工作的清楚工具。\n",
        encoding="utf-8",
    )
    (tmp_path / "ROADMAP.md").write_text(
        "# Product plan\n\n## P0：先完成主要流程\n\n"
        "### 1. 讓使用者看懂目前狀態（已完成第一版）\n\n"
        "問題：使用者現在不知道下一步。\n\n驗收：\n\n- 顯示下一步。\n- 顯示資料缺口。\n",
        encoding="utf-8",
    )

    preview_response = client.post("/api/imports/local/preview", json={"path": str(tmp_path)})
    assert preview_response.status_code == 200
    preview = preview_response.json()

    confirm_response = client.post(
        "/api/projects",
        json={
            "preview_id": preview["preview_id"],
            "display_name": "Helpful Project",
            "purpose": preview["understanding"]["plain_language_purpose"],
        },
    )
    assert confirm_response.status_code == 201
    project = confirm_response.json()
    assert project["name"] == "Helpful Project"
    assert project["plan_status"] == "draft"
    assert project["plan"][0]["children"][0]["title"] == "P0：先完成主要流程"
    assert project["plan"][0]["children"][0]["children"][0]["acceptance_total"] == 2

    confirmed = client.post(f"/api/projects/{project['id']}/plan/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["plan_status"] == "confirmed"
    assert confirmed.json()["plan"][0]["state"] == "in_progress"

    refreshed = client.post(f"/api/projects/{project['id']}/plan/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["plan_status"] == "confirmed"
    assert "未發現結構變更" in refreshed.json()["plan"][0]["state_explanation"]

    portfolio = client.get("/api/portfolio").json()
    assert len(portfolio["projects"]) == 1

    child_preview = client.post("/api/imports/local/preview", json={"path": str(tmp_path)}).json()
    child_response = client.post(
        "/api/projects",
        json={
            "preview_id": child_preview["preview_id"],
            "display_name": "Helpful Project Web",
            "purpose": "讓使用者能看懂 Helpful Project。",
            "parent_project_id": project["id"],
        },
    )
    assert child_response.status_code == 201
    assert child_response.json()["parent_project_id"] == project["id"]

    portfolio = client.get("/api/portfolio").json()
    assert len(portfolio["projects"]) == 2

    created_decision = client.post(
        f"/api/projects/{project['id']}/decisions",
        json={"question": "這個狀態為什麼還不能算完成？", "context": "我需要知道缺少哪些證據。"},
    )
    assert created_decision.status_code == 201
    decision = created_decision.json()
    assert decision["status"] == "waiting_agent"

    follow_up = client.post(
        f"/api/projects/{project['id']}/decisions/{decision['id']}/messages",
        json={"body": "請列出具體的測試與人工驗收。"},
    )
    assert follow_up.status_code == 200
    assert len(follow_up.json()["messages"]) == 2

    answered = client.post(
        f"/api/projects/{project['id']}/decisions/{decision['id']}/answer",
        json={"answer": "先補齊契約測試，再做人工驗收。"},
    )
    assert answered.status_code == 200
    assert answered.json()["status"] == "answered"
    assert answered.json()["answer"] == "先補齊契約測試，再做人工驗收。"
