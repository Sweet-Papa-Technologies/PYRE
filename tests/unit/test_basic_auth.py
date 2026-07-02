"""v1.1 Phase 5: HTTP Basic auth middleware (RFC 7617)."""

import base64
import hashlib
import json

from pyre import App, Request, Response, auth


def make_request(method="GET", path="/", headers=None):
    return Request(method, path, headers=headers or {})


def run_update(app, request):
    gen = app.handle_update(request)
    try:
        next(gen)
        raise AssertionError("plain handler should not yield")
    except StopIteration as stop:
        return stop.value


def basic_header(username, password, scheme="Basic"):
    raw = ("%s:%s" % (username, password)).encode("utf-8")
    return {"authorization": "%s %s" % (scheme, base64.b64encode(raw).decode("ascii"))}


def sha(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def protected_app(users=None, **kwargs):
    app = App()
    if users is None:
        users = {"alice": sha("s3cret")}
    app.before_request(auth.require_basic(users=users, exempt=("/health",), **kwargs))

    @app.get("/health")
    def health(req):
        return Response.json({"status": "ok"})

    @app.get("/private")
    def private(req):
        return Response.json({"user": getattr(req, "user", None)})

    return app


def test_valid_creds_dict_hashed():
    app = protected_app()
    response = app.handle_query(
        make_request(path="/private", headers=basic_header("alice", "s3cret"))
    )
    assert response.status == 200
    assert json.loads(response.body)["user"] == "alice"


def test_valid_creds_dict_plaintext():
    app = protected_app(users={"bob": "hunter2"})
    response = app.handle_query(
        make_request(path="/private", headers=basic_header("bob", "hunter2"))
    )
    assert response.status == 200


def test_valid_creds_callable():
    app = protected_app(users=lambda u, p: u == "carol" and p == "pw")
    response = app.handle_query(
        make_request(path="/private", headers=basic_header("carol", "pw"))
    )
    assert response.status == 200
    bad = run_update(app, make_request(path="/private", headers=basic_header("carol", "nope")))
    assert bad.status == 401


def test_wrong_password_401():
    app = protected_app()
    response = run_update(
        app, make_request(path="/private", headers=basic_header("alice", "wrong"))
    )
    assert response.status == 401


def test_unknown_user_401():
    app = protected_app()
    response = run_update(
        app, make_request(path="/private", headers=basic_header("mallory", "s3cret"))
    )
    assert response.status == 401


def test_missing_header_401_with_challenge_and_envelope():
    app = protected_app(realm="vault")
    response = run_update(app, make_request(path="/private"))
    assert response.status == 401
    assert ("www-authenticate", 'Basic realm="vault"') in response.headers
    assert json.loads(response.body) == {"error": "unauthorized"}


def test_default_realm_is_pyre():
    app = protected_app()
    response = run_update(app, make_request(path="/private"))
    assert ("www-authenticate", 'Basic realm="pyre"') in response.headers


def test_wrong_scheme_401():
    app = protected_app()
    for headers in (
        {"authorization": "Bearer tok-1"},
        basic_header("alice", "s3cret", scheme="Digest"),
    ):
        response = run_update(app, make_request(path="/private", headers=headers))
        assert response.status == 401, headers


def test_scheme_case_insensitive_and_whitespace_tolerant():
    app = protected_app()
    b64 = base64.b64encode(b"alice:s3cret").decode("ascii")
    for value in ("basic %s" % b64, "BASIC  %s " % b64, "  Basic %s" % b64):
        response = app.handle_query(
            make_request(path="/private", headers={"authorization": value})
        )
        assert response.status == 200, value


def test_malformed_base64_401_not_500():
    app = protected_app()
    for garbage in ("Basic !!!not-base64!!!", "Basic abc", "Basic éé", "Basic"):
        response = run_update(
            app, make_request(path="/private", headers={"authorization": garbage})
        )
        assert response.status == 401, garbage


def test_no_colon_in_decoded_creds_401():
    app = protected_app()
    b64 = base64.b64encode(b"alice-no-colon").decode("ascii")
    response = run_update(
        app, make_request(path="/private", headers={"authorization": "Basic " + b64})
    )
    assert response.status == 401


def test_non_utf8_credential_bytes_401_not_500():
    app = protected_app()
    b64 = base64.b64encode(b"\xff\xfe:\xff").decode("ascii")
    response = run_update(
        app, make_request(path="/private", headers={"authorization": "Basic " + b64})
    )
    assert response.status == 401


def test_unicode_credentials():
    app = protected_app(users={"josé": sha("paßword☃")})
    ok = app.handle_query(
        make_request(path="/private", headers=basic_header("josé", "paßword☃"))
    )
    assert ok.status == 200
    assert json.loads(ok.body)["user"] == "josé"
    bad = run_update(
        app, make_request(path="/private", headers=basic_header("josé", "paßword"))
    )
    assert bad.status == 401


def test_exempt_path_open():
    app = protected_app()
    response = app.handle_query(make_request(path="/health"))
    assert response.status == 200


def test_options_exempt_for_cors_preflight():
    app = protected_app()
    app.enable_cors(origins="*")
    response = app.handle_query(
        make_request("OPTIONS", "/private", headers={"origin": "https://a.example"})
    )
    assert response.status == 204


def test_username_attached_to_request():
    app = protected_app()
    seen = {}

    @app.get("/whoami")
    def whoami(req):
        seen["user"] = req.user
        return Response.json({"user": req.user})

    response = app.handle_query(
        make_request(path="/whoami", headers=basic_header("alice", "s3cret"))
    )
    assert response.status == 200
    assert seen["user"] == "alice"


def test_works_alongside_errorhandler():
    app = protected_app()

    @app.errorhandler(404)
    def not_found(req, info):
        return Response.json({"custom": "lost", "path": info["path"]}, status=404)

    # Framework 404 still reaches the custom handler (auth failure on an
    # unknown path yields 401 first — before hooks run after routing).
    missing = run_update(
        app, make_request(path="/nope", headers=basic_header("alice", "s3cret"))
    )
    assert missing.status == 404
    assert json.loads(missing.body)["custom"] == "lost"

    # The 401 short-circuit keeps its own envelope, untouched by handlers.
    denied = run_update(app, make_request(path="/private"))
    assert denied.status == 401
    assert json.loads(denied.body) == {"error": "unauthorized"}
