"""Standalone authorization boundary; fleet enrollment is not implemented yet.

This module accepts the transport peer address, never forwarded request headers.
Runtime permissions are server configuration, independent of UI confirmations.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import hmac
import ipaddress
import os
from typing import Mapping
from urllib.parse import urlsplit


RUNTIME_ACTIONS = frozenset({
    "agent.start", "agent.message", "shell.create", "shell.execute", "run.stop",
})
LOCAL_ACTIONS = frozenset({"local.read", "local.write"})
DEFAULT_BROWSER_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})


class SecurityError(Exception):
    """Safe error details for HTTP responses and denial audit records."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Principal:
    id: str
    authentication: str


@dataclass(frozen=True)
class SecurityPolicy:
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    allowed_actions: frozenset[str] = frozenset()
    allowed_origins: frozenset[str] = DEFAULT_BROWSER_ORIGINS


def load_security_policy(environ: Mapping[str, str] | None = None) -> SecurityPolicy:
    """Validate at startup AND per request so a changed config fails closed."""
    values = os.environ if environ is None else environ
    mode = values.get("CONTROL_CENTER_MODE", "standalone").strip().lower()
    if mode != "standalone":
        raise SecurityError(503, "deployment_mode_unavailable", "目前僅支援單機模式；多人節點授權尚未啟用。")
    username = values.get("CONTROL_CENTER_USER") or None
    password = values.get("CONTROL_CENTER_PASSWORD") or None
    if bool(username) != bool(password):
        raise SecurityError(503, "incomplete_credentials", "登入設定不完整；帳號與密碼必須同時設定。")
    actions = frozenset(part.strip() for part in values.get("CONTROL_CENTER_ALLOWED_ACTIONS", "").split(",") if part.strip())
    if not actions <= RUNTIME_ACTIONS:
        raise SecurityError(503, "invalid_action_configuration", "執行權限設定包含不支援的動作。")
    origins = frozenset(part.strip() for part in values.get(
        "CONTROL_CENTER_ALLOWED_ORIGINS", ",".join(sorted(DEFAULT_BROWSER_ORIGINS)),
    ).split(",") if part.strip())
    if any(not _valid_origin(origin) for origin in origins):
        raise SecurityError(503, "invalid_origin_configuration", "瀏覽器來源必須是完整的 HTTP 或 HTTPS origin，不可包含萬用字元或路徑。")
    return SecurityPolicy(username, password, actions, origins)


def _valid_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
            and not parsed.username and not parsed.password and not parsed.path
            and not parsed.query and not parsed.fragment and "*" not in value
            and not any(char.isspace() for char in value)
        )
    except ValueError:
        return False


def validate_request_origin(
    origin: str | None,
    fetch_site: str | None,
    request_origin: str,
    policy: SecurityPolicy | None = None,
) -> None:
    """Check mutations before side effects; request_origin must not trust forwarded headers.

    CLI requests without browser headers remain supported. This is separate from
    authentication and must also run for authenticated Basic users.
    """
    policy = load_security_policy() if policy is None else policy
    if origin is not None:
        if _valid_origin(origin) and (
            origin in policy.allowed_origins
            or (_valid_origin(request_origin) and origin == request_origin)
        ):
            return
        raise SecurityError(403, "origin_not_allowed", "此瀏覽器來源未獲允許執行操作。")
    if fetch_site and fetch_site.strip().lower() == "cross-site":
        raise SecurityError(403, "origin_not_allowed", "跨網站操作缺少可驗證的來源。")


def _is_loopback(client_host: str | None) -> bool:
    try:
        address = ipaddress.ip_address(client_host or "")
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def authenticate_request(
    authorization: str | None,
    client_host: str | None,
    policy: SecurityPolicy | None = None,
) -> Principal:
    policy = load_security_policy() if policy is None else policy
    if not policy.username and not policy.password:
        if _is_loopback(client_host):
            return Principal("local-owner", "loopback")
        raise SecurityError(401, "authentication_required", "遠端存取必須先設定並驗證登入帳密。")
    # Also reject manually constructed half-configured policies.
    if not policy.username or not policy.password:
        raise SecurityError(503, "incomplete_credentials", "登入設定不完整；帳號與密碼必須同時設定。")
    try:
        if not authorization or len(authorization) > 8192:
            raise ValueError("invalid header")
        scheme, encoded = authorization.split(" ", 1)
        if scheme.lower() != "basic":
            raise ValueError("invalid scheme")
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        supplied_user, supplied_password = decoded.split(":", 1)
        user_matches = hmac.compare_digest(supplied_user.encode("utf-8"), policy.username.encode("utf-8"))
        password_matches = hmac.compare_digest(supplied_password.encode("utf-8"), policy.password.encode("utf-8"))
    except (ValueError, UnicodeError, binascii.Error):
        raise SecurityError(401, "authentication_required", "需要有效的登入帳密。") from None
    if not (user_matches and password_matches):
        raise SecurityError(401, "authentication_required", "需要有效的登入帳密。")
    return Principal("local-owner", "basic")


def authorize_action(
    principal: Principal,
    action: str,
    policy: SecurityPolicy | None = None,
) -> None:
    policy = load_security_policy() if policy is None else policy
    if principal.id != "local-owner" or principal.authentication not in {"basic", "loopback"}:
        raise SecurityError(403, "action_not_authorized", "目前身分沒有此操作權限。")
    if action in LOCAL_ACTIONS:
        return
    if action in RUNTIME_ACTIONS and action in policy.allowed_actions:
        return
    raise SecurityError(403, "action_not_authorized", "此操作尚未在本機執行權限設定中開啟。")
