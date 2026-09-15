"""Small dependency-free client for the notify-only goal monitor API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _base_url() -> str:
    return os.environ.get("CONTROL_CENTER_API", "http://127.0.0.1:8765").rstrip("/")


def _request(method: str, path: str, payload: dict | None = None) -> object:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    user = os.environ.get("CONTROL_CENTER_USER")
    password = os.environ.get("CONTROL_CENTER_PASSWORD")
    if bool(user) != bool(password):
        raise RuntimeError("CONTROL_CENTER_USER and CONTROL_CENTER_PASSWORD must be set together")
    if user and password:
        token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = Request(f"{_base_url()}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Control Center returned HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Cannot reach Control Center at {_base_url()}: {error.reason}") from error


def _path(project_id: str, monitor_id: str, suffix: str = "") -> str:
    project = quote(project_id, safe="")
    monitor = quote(monitor_id, safe="")
    return f"/api/projects/{project}/monitors/{monitor}{suffix}"


def command_monitor(project_id: str, monitor_id: str) -> object:
    monitors = _request("GET", f"/api/projects/{quote(project_id, safe='')}/monitors")
    if not isinstance(monitors, list):
        raise RuntimeError("Control Center returned an invalid monitor list")
    match = next((item for item in monitors if item.get("id") == monitor_id), None)
    if match is None:
        raise RuntimeError(f"Monitor {monitor_id} was not found in project {project_id}")
    return match


def command_snapshot(project_id: str, monitor_id: str) -> object:
    return _request("POST", _path(project_id, monitor_id, "/snapshot"))


def command_report(project_id: str, monitor_id: str, file_path: str) -> object:
    payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Finding file must contain one JSON object")
    return _request("POST", _path(project_id, monitor_id, "/findings"), payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("monitor", "snapshot"):
        child = subparsers.add_parser(name)
        child.add_argument("project_id")
        child.add_argument("monitor_id")
    report = subparsers.add_parser("report")
    report.add_argument("project_id")
    report.add_argument("monitor_id")
    report.add_argument("--file", required=True)
    args = parser.parse_args()

    if os.environ.get("HERDR_ENV") != "1":
        raise RuntimeError("This monitor must run inside Herdr (HERDR_ENV=1)")
    if args.command == "monitor":
        result = command_monitor(args.project_id, args.monitor_id)
    elif args.command == "snapshot":
        result = command_snapshot(args.project_id, args.monitor_id)
    else:
        result = command_report(args.project_id, args.monitor_id, args.file)
    # ASCII escapes keep JSON machine-readable in Windows panes that still use
    # a legacy console code page. Consumers decode the JSON values normally.
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
