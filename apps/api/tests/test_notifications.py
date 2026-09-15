from concurrent.futures import ThreadPoolExecutor
import asyncio
import base64
import sqlite3
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from httpx import BasicAuth

from control_center.store import Store
from control_center.notifications import NotificationStore, NotificationPreferences, emit_event


def make_store(tmp_path):
    store = Store(tmp_path / "notices.db")
    now = datetime.now(timezone.utc).isoformat()
    with store._connect() as c:
        c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "project-1", "local", None, "Project", "Purpose", "local_repository", str(tmp_path),
            "high", "confirmed", None, "[]", "[]", now, now))
    return store


def emit(store, index):
    with store._connect() as c:
        return emit_event(c, source_key=f"source-event:{index}", event_type="agent.turn_completed",
                          project_id="project-1", entity_id="session-1")


def test_database_handles_close_after_each_transaction(tmp_path):
    store = make_store(tmp_path)
    with store._connect() as connection:
        connection.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with pytest.raises(RuntimeError):
        with store._connect() as failed:
            failed.execute("INSERT INTO collector_health VALUES ('test','healthy','now')")
            raise RuntimeError("abort")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        failed.execute("SELECT 1")
    with store._connect() as reopened:
        assert reopened.execute("SELECT COUNT(*) FROM collector_health").fetchone()[0] == 0


def test_duplicate_events_and_transaction_rollback(tmp_path):
    store = make_store(tmp_path)
    inbox = NotificationStore(store._connect)
    with ThreadPoolExecutor(max_workers=4) as workers:
        ids = list(workers.map(lambda _: emit(store, 1), range(12)))
    assert len(set(ids)) == 1
    with pytest.raises(RuntimeError):
        with store._connect() as c:
            emit_event(c, source_key="rolled-back", event_type="work.verified", project_id="project-1")
            raise RuntimeError("simulate failure before commit")
    assert inbox.page("local-owner").unread_count == 1
    reopened = NotificationStore(Store(store.path)._connect)
    assert reopened.page("local-owner").items[0].id == ids[0]
    assert reopened.page("other-user").items == []
    with pytest.raises(KeyError):
        reopened.read("other-user", ids[0], True)


def test_baseline_tail_pagination_and_read_all_preserve_new_items(tmp_path):
    store = make_store(tmp_path)
    inbox = NotificationStore(store._connect)
    for n in range(8):
        emit(store, n)
    baseline = inbox.page("local-owner", limit=3)
    assert [x.sequence for x in baseline.items] == [6, 7, 8]
    assert baseline.high_watermark == 8 and baseline.next_cursor == 5
    old = inbox.page("local-owner", limit=3, before=baseline.next_cursor)
    assert [x.sequence for x in old.items] == [3, 4, 5]
    # This event lands between HTTP snapshot and SSE establishment.
    emit(store, 9)
    tail = inbox.page("local-owner", after=baseline.high_watermark, tail=True)
    assert [x.sequence for x in tail.items] == [9]
    inbox.read_all("local-owner", baseline.high_watermark)
    assert inbox.page("local-owner").unread_count == 1
    initial_tail = inbox.page("local-owner", after=0, limit=3, tail=True)
    assert [x.sequence for x in initial_tail.items] == [1, 2, 3]
    assert initial_tail.next_cursor == 3


def test_summary_never_copies_source_secrets_and_preferences_do_not_delete_history(tmp_path):
    store = make_store(tmp_path)
    inbox = NotificationStore(store._connect)
    with store._connect() as c:
        emit_event(c, source_key="private-source", event_type="agent.goal_completed", project_id="project-1",
                   identity={"private": "example-not-a-real-secret"})
    prefs = NotificationPreferences(desktop_enabled=True, event_types=[], project_ids=[])
    inbox.save_preferences("local-owner", prefs)
    assert inbox.preferences("local-owner") == prefs
    assert "example-not-a-real-secret" not in inbox.page("local-owner").model_dump_json()
    assert len(inbox.page("local-owner").items) == 1
    with pytest.raises(ValueError):
        inbox.save_preferences("local-owner", NotificationPreferences(project_ids=["missing"]))
    with pytest.raises(ValueError):
        NotificationPreferences(quiet_start="22:00")


@pytest.fixture
def api(tmp_path, monkeypatch):
    from control_center import main
    local = make_store(tmp_path)
    monkeypatch.setattr(main.store, "path", local.path)
    monkeypatch.setenv("CONTROL_CENTER_USER", "test-owner")
    monkeypatch.setenv("CONTROL_CENTER_PASSWORD", "test-password")
    monkeypatch.setenv("CONTROL_CENTER_ALLOWED_ACTIONS", "")
    monkeypatch.setenv("CONTROL_CENTER_MODE", "standalone")
    client = TestClient(main.app)
    client.auth = BasicAuth("test-owner", "test-password")
    return main, client


def test_notification_api_auth_read_and_configuration(api):
    main, client = api
    event_id = emit(main.store, 1)
    assert client.get("/api/notifications", auth=("wrong", "wrong")).status_code == 401
    response = client.get("/api/notifications").json()
    assert response["items"][0]["id"] == event_id
    assert client.patch(f"/api/notifications/{event_id}", json={"read": True}).status_code == 200
    assert client.get("/api/notifications").json()["unread_count"] == 0
    assert client.get("/api/notifications?after=-1").status_code == 422
    assert client.put("/api/notification-preferences", json={"timezone": "not-a-zone"}).status_code == 422
    assert client.put("/api/notification-preferences", json={"event_types": []}).status_code == 200


@pytest.mark.parametrize("path", [
    "/api/projects/project-1/agents/wN:p1/messages", "/api/projects/project-1/agents/start",
    "/api/projects/project-1/shell", "/api/projects/project-1/shell/wN:p1/commands",
])
def test_each_runtime_route_is_denied_before_runtime_and_audited(api, monkeypatch, path):
    main, client = api
    def forbidden(*args, **kwargs):
        pytest.fail("unauthorized request reached runtime")
    for name in ("list_project_agents", "start_project_agent", "create_project_shell", "run_shell_command", "send_agent_message"):
        monkeypatch.setattr(main, name, forbidden)
    response = client.post(path, json={"confirm_dangerous": True})
    assert response.status_code == 403
    with main.store._connect() as c:
        row = c.execute("SELECT * FROM security_audit ORDER BY rowid DESC LIMIT 1").fetchone()
    assert row["outcome"] == "action_not_authorized"
    assert row["actor"] == "local-owner"
    assert "{project_id}" in row["target"]


def test_cross_origin_mutations_rejected_and_fleet_stays_unavailable(api, monkeypatch):
    _, client = api
    response = client.post("/api/notifications/read-all", json={"through_sequence": 100}, headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403
    assert response.json()["code"] == "origin_not_allowed"
    monkeypatch.setenv("CONTROL_CENTER_MODE", "fleet")
    assert client.get("/api/notifications").status_code == 503


def test_auth_is_enforced_for_every_registered_mutation(api, monkeypatch):
    main, client = api
    for route in main.app.routes:
        methods = getattr(route, "methods", set())
        for method in methods - {"GET", "HEAD", "OPTIONS"}:
            path = route.path
            import re
            path = re.sub(r"\{[^}]+\}", "test-id", path)
            result = client.request(method, path, json={}, auth=("wrong", "wrong"))
            assert result.status_code == 401, (method, path, result.status_code)


def test_notification_stream_resumes_exactly_and_rechecks_authorization(api, monkeypatch):
    main, _ = api
    for index in range(3):
        emit(main.store, index)

    class Request:
        headers = {"authorization": "Basic " + base64.b64encode(b"test-owner:test-password").decode(), "last-event-id": "2"}
        client = SimpleNamespace(host="127.0.0.1")

        async def is_disconnected(self):
            return False

    async def check():
        response = await main.notifications_stream(Request(), after=0)
        iterator = response.body_iterator
        event = await anext(iterator)
        assert event.startswith("id: 3\nevent: notification\n")
        monkeypatch.setenv("CONTROL_CENTER_PASSWORD", "changed-password")
        event = await anext(iterator)
        assert "authorization_changed" in event
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        await iterator.aclose()

    asyncio.run(check())


def test_notification_stream_rejects_future_cursor(api):
    main, _ = api

    class Request:
        headers = {"authorization": "Basic " + base64.b64encode(b"test-owner:test-password").decode(), "last-event-id": "900"}
        client = SimpleNamespace(host="127.0.0.1")

        async def is_disconnected(self):
            return False

    async def check():
        response = await main.notifications_stream(Request(), after=0)
        iterator = response.body_iterator
        assert "cursor_reset" in await anext(iterator)
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    asyncio.run(check())


def test_reused_pane_does_not_inherit_another_runtime_request(api, monkeypatch):
    main, client = api
    from control_center.models import AgentSession, AgentSessionsResponse

    def source(session_id, request=None):
        return AgentSessionsResponse(connected=True, source="synthetic", limitation="fixture", agents=[
            AgentSession(id="pane-1", provider="codex", status="working", workspace_id="fixture",
                         workspace_label="fixture", pane_id="pane-1", cwd="fixture", title="fixture",
                         task_summary="fixture", runtime_session_id=session_id, latest_human_request=request)
        ])

    monkeypatch.setattr(main, "list_project_agents", lambda _: source("session-A", "First runtime request"))
    first = client.get("/api/projects/project-1/agents").json()["agents"][0]
    assert first["can_send_message"] is False
    monkeypatch.setattr(main, "list_project_agents", lambda _: source("session-B"))
    assert client.get("/api/projects/project-1/agents").json()["agents"][0]["latest_human_request"] is None
    monkeypatch.setattr(main, "list_project_agents", lambda _: source(None))
    assert client.get("/api/projects/project-1/agents").json()["agents"][0]["latest_human_request"] is None
    monkeypatch.setattr(main, "list_project_agents", lambda _: source("session-A"))
    assert client.get("/api/projects/project-1/agents").json()["agents"][0]["latest_human_request"] == "First runtime request"


def test_background_collection_recovers_from_transient_database_failure(api, monkeypatch):
    main, _ = api
    calls = []
    sleeps = []

    def poll():
        calls.append(True)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database temporarily locked")

    async def sleep(_seconds):
        sleeps.append(True)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(main.store, "portfolio", lambda: SimpleNamespace(projects=[]))
    monkeypatch.setattr(main.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._event_collection_loop(SimpleNamespace(poll=poll)))
    assert len(calls) == 2
