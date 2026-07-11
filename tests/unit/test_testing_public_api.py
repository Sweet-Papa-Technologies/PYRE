from pyre import App, Response
from pyre.testing import PyreTestClient, WasmBuildCache, real_toolchain_problems
from pyre.testing import install_kybra_stubs


def test_in_process_http_methods_and_response_normalization():
    app = App()

    @app.get("/health")
    def health(req):
        return Response.json({"ok": True})

    @app.post("/echo", update=True)
    def echo(req):
        return Response.json(req.json())

    client = PyreTestClient.from_app(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.raw["status_code"] == 200
    assert client.post("/echo", json_body={"b": 2, "a": 1}).json() == {"a": 1, "b": 2}


def test_identity_is_deterministic_and_replaceable():
    app = App()
    @app.get("/caller")
    def caller(req): return {"caller": req.caller}
    default = PyreTestClient.from_app(app)
    selected = default.with_caller("aaaaa-aa")
    assert default.get("/caller").json()["caller"] == "2vxsx-fae"
    assert selected.get("/caller").json()["caller"] == "aaaaa-aa"


def test_self_contained_kybra_stubs_cover_template_surface(monkeypatch):
    fake_ic = install_kybra_stubs(monkeypatch, now_ns=42)
    from kybra import Async, Query, Record, StableBTreeMap, init, nat64
    from kybra.canisters.management import HttpResponse, management_canister

    class Example(Record, total=False):
        value: nat64

    assert Async[Example] is Async
    assert Query[[nat64], Example] is Query
    backend = StableBTreeMap[str, str](memory_id=250)
    backend.insert("a", "b"); assert backend.get("a") == "b"
    assert init(lambda: None)() is None
    assert HttpResponse is dict and management_canister.raw_rand() is not None
    assert fake_ic.time() == 42


def test_offline_pocketic_controls_and_status():
    app = App()
    offline = PyreTestClient.offline_pocketic(app)
    before = offline.now_ns
    offline.advance_time(seconds=2); offline.add_cycles(5); offline.tick()
    status = offline.canister_status()
    assert offline.now_ns == before + 2_000_000_000
    assert status["mock"] is True and status["status"] == "running"


def test_wasm_build_cache_is_content_addressed_and_no_cache_rebuilds(tmp_path):
    (tmp_path / "src").mkdir(); (tmp_path / "src/app.py").write_text("value = 1\n")
    cache = WasmBuildCache(tmp_path)
    calls = []
    def build(): calls.append(True); return b"wasm-" + str(len(calls)).encode()
    first, hit = cache.get_or_build(build); assert hit is False
    second, hit = cache.get_or_build(build); assert hit is True and second == first
    third, hit = cache.get_or_build(build, no_cache=True)
    assert hit is False and third != first and len(calls) == 2
    (tmp_path / "src/app.py").write_text("value = 2\n")
    _fourth, hit = cache.get_or_build(build); assert hit is False and len(calls) == 3


def test_random_identity_is_explicit_and_toolchain_guidance_is_actionable():
    app = App(); deterministic = PyreTestClient.from_app(app)
    random_client = deterministic.with_random_caller()
    assert deterministic.caller == "2vxsx-fae"
    assert random_client.caller.startswith("host-test-") and random_client.caller != deterministic.caller
    guidance = "\n".join(real_toolchain_problems())
    assert "Python 3.10.7" in guidance and "kybra==0.7.1" in guidance


def test_in_process_client_can_resolve_yielded_platform_calls():
    app = App(); calls = []
    @app.post("/raw", update=True)
    def raw(_request):
        reply = yield "fake-kybra-call"
        return {"reply": reply["Ok"]}
    client = PyreTestClient.from_app(app).with_call_resolver(
        lambda call: calls.append(call) or {"Ok": "stubbed"})
    assert client.post("/raw").json() == {"reply": "stubbed"}
    assert calls == ["fake-kybra-call"]
