import base64

import pytest

from control_center.security import (
    Principal,
    RUNTIME_ACTIONS,
    SecurityError,
    authenticate_request,
    authorize_action,
    load_security_policy,
    validate_request_origin,
)


def basic(value: str) -> str:
    return "Basic " + base64.b64encode(value.encode("utf-8")).decode("ascii")


@pytest.mark.parametrize("values", [
    {"CONTROL_CENTER_USER": "owner"},
    {"CONTROL_CENTER_PASSWORD": "secret"},
    {"CONTROL_CENTER_USER": "owner", "CONTROL_CENTER_PASSWORD": ""},
])
def test_partial_credentials_fail_closed(values):
    with pytest.raises(SecurityError) as error:
        load_security_policy(values)
    assert (error.value.status_code, error.value.code) == (503, "incomplete_credentials")


@pytest.mark.parametrize("mode", ["fleet", "Fleet", "unknown", ""])
def test_unimplemented_or_invalid_mode_fails_closed(mode):
    with pytest.raises(SecurityError) as error:
        load_security_policy({"CONTROL_CENTER_MODE": mode})
    assert error.value.status_code == 503


@pytest.mark.parametrize("header", [
    None, "", "Basic", "Bearer token", "Basic !!!", "Basic YQ", "Basic /w==",
    "Basic 資料", basic("missing-colon"), basic("owner:wrong"), basic("別人:secret"),
    "Basic " + "A" * 9000,
])
def test_malformed_or_wrong_basic_auth_is_401(header):
    policy = load_security_policy({"CONTROL_CENTER_USER": "owner", "CONTROL_CENTER_PASSWORD": "secret"})
    with pytest.raises(SecurityError) as error:
        authenticate_request(header, "127.0.0.1", policy)
    assert error.value.status_code == 401
    assert "secret" not in str(error.value)


def test_unicode_credentials_and_colon_in_password_are_valid():
    policy = load_security_policy({"CONTROL_CENTER_USER": "擁有者", "CONTROL_CENTER_PASSWORD": "密碼:abc"})
    principal = authenticate_request(basic("擁有者:密碼:abc"), "203.0.113.1", policy)
    assert principal == Principal("local-owner", "basic")
    assert "密碼" not in repr(policy)


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_unconfigured_standalone_allows_actual_loopback(peer):
    principal = authenticate_request(None, peer, load_security_policy({}))
    assert principal == Principal("local-owner", "loopback")


@pytest.mark.parametrize("peer", [None, "localhost", "testclient", "10.0.0.1", "203.0.113.1", "::ffff:10.0.0.1"])
def test_unconfigured_standalone_denies_other_peers(peer):
    with pytest.raises(SecurityError) as error:
        authenticate_request(None, peer, load_security_policy({}))
    assert error.value.status_code == 401


@pytest.mark.parametrize("action", sorted(RUNTIME_ACTIONS))
def test_runtime_actions_are_denied_by_default_even_for_authenticated_owner(action):
    with pytest.raises(SecurityError) as error:
        authorize_action(Principal("local-owner", "basic"), action, load_security_policy({}))
    assert (error.value.status_code, error.value.code) == (403, "action_not_authorized")


def test_allowlist_grants_only_exact_configured_action():
    policy = load_security_policy({"CONTROL_CENTER_ALLOWED_ACTIONS": " agent.message, agent.message "})
    owner = Principal("local-owner", "basic")
    authorize_action(owner, "agent.message", policy)
    for action in RUNTIME_ACTIONS - {"agent.message"}:
        with pytest.raises(SecurityError):
            authorize_action(owner, action, policy)
    for action in ["shell.execute.confirm_dangerous", "unknown", "*"]:
        with pytest.raises(SecurityError):
            authorize_action(owner, action, policy)


@pytest.mark.parametrize("action", ["*", "agent.*", "unknown", "local.write"])
def test_unknown_configured_actions_are_configuration_errors(action):
    with pytest.raises(SecurityError) as error:
        load_security_policy({"CONTROL_CENTER_ALLOWED_ACTIONS": action})
    assert error.value.status_code == 503


def test_local_data_actions_require_authenticated_owner():
    policy = load_security_policy({})
    for action in ["local.read", "local.write"]:
        authorize_action(Principal("local-owner", "loopback"), action, policy)
        for principal in [Principal("another-user", "basic"), Principal("local-owner", "unverified")]:
            with pytest.raises(SecurityError):
                authorize_action(principal, action, policy)


def test_environment_policy_is_revalidated_on_each_request(monkeypatch):
    for key in ["CONTROL_CENTER_USER", "CONTROL_CENTER_PASSWORD", "CONTROL_CENTER_ALLOWED_ACTIONS"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CONTROL_CENTER_MODE", "standalone")
    assert authenticate_request(None, "127.0.0.1").id == "local-owner"
    monkeypatch.setenv("CONTROL_CENTER_MODE", "fleet")
    with pytest.raises(SecurityError) as error:
        authenticate_request(None, "127.0.0.1")
    assert error.value.status_code == 503


@pytest.mark.parametrize("origin", ["https://control.example", "http://127.0.0.1:5173", "http://localhost:5173"])
def test_mutation_accepts_exact_origin_or_explicit_development_origin(origin):
    validate_request_origin(origin, "cross-site", "https://control.example", load_security_policy({}))


@pytest.mark.parametrize("origin", ["null", "", "https://evil.example", "https://control.example.evil", "https://control.example:444", "https://control.example/", "https://user@control.example"])
def test_mutation_rejects_untrusted_or_opaque_origin(origin):
    with pytest.raises(SecurityError) as error:
        validate_request_origin(origin, "same-origin", "https://control.example", load_security_policy({}))
    assert (error.value.status_code, error.value.code) == (403, "origin_not_allowed")


def test_cross_site_without_origin_is_rejected_but_cli_remains_supported():
    policy = load_security_policy({})
    with pytest.raises(SecurityError):
        validate_request_origin(None, "cross-site", "http://127.0.0.1:8765", policy)
    validate_request_origin(None, None, "http://127.0.0.1:8765", policy)


def test_origin_config_can_disable_development_exceptions():
    policy = load_security_policy({"CONTROL_CENTER_ALLOWED_ORIGINS": ""})
    with pytest.raises(SecurityError):
        validate_request_origin("http://localhost:5173", "same-site", "http://localhost:8765", policy)
    policy = load_security_policy({"CONTROL_CENTER_ALLOWED_ORIGINS": "https://ui.example"})
    validate_request_origin("https://ui.example", "cross-site", "https://api.example", policy)


@pytest.mark.parametrize("origin", ["*", "https://*.example", "null", "https://ui.example/path", "https://user:password@ui.example", "https://ui.example:99999", "https://ui.example:0"])
def test_invalid_origin_configuration_fails_closed(origin):
    with pytest.raises(SecurityError) as error:
        load_security_policy({"CONTROL_CENTER_ALLOWED_ORIGINS": origin})
    assert error.value.code == "invalid_origin_configuration"
