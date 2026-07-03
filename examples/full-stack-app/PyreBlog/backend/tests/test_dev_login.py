"""The local-only 'dev' login provider gate (used for on-canister e2e).

It mints a session from a plaintext token with NO signature check, and is
enabled ONLY when the auth:dev_login kv flag is set (bearer-gated). Off by
default so a default/mainnet deploy can never mint dev sessions. The real
RS256/ES256 verify path is proven natively in examples/oidc_spike.
"""

from conftest import api, body_json


def _enable_dev(app):
    resp = api(app, "PUT", "/api/meta", body={"dev_login": True}, auth=True)
    assert resp.status == 200


def test_dev_provider_disabled_by_default_400(app):
    resp = api(app, "POST", "/api/auth/login",
               body={"provider": "dev", "token": "reader"})
    assert resp.status == 400  # unsupported/unconfigured provider


def test_dev_provider_mints_session_when_enabled(app):
    _enable_dev(app)
    resp = api(app, "POST", "/api/auth/login",
               body={"provider": "dev", "token": "reader-sub|reader@x.io|Ada Reader"})
    assert resp.status == 200
    data = body_json(resp)
    assert len(data["session_id"]) == 64
    assert data["identity"] == "reader-sub"
    assert data["email"] == "reader@x.io"
    assert data["name"] == "Ada Reader"


def test_dev_provider_defaults_email_name_from_sub(app):
    _enable_dev(app)
    data = body_json(api(app, "POST", "/api/auth/login",
                         body={"provider": "dev", "token": "solo"}))
    assert data["identity"] == "solo"
    assert data["email"] == "solo@dev.local"
    assert data["name"] == "solo"


def test_dev_provider_empty_subject_rejected(app):
    _enable_dev(app)
    resp = api(app, "POST", "/api/auth/login",
               body={"provider": "dev", "token": "  "})
    assert resp.status in (400, 401)
