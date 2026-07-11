"""Supported host-side test client for in-process PYRE applications.

PocketIC support is optional; importing this module never imports pytest or
pocket_ic.  Canister builds fail early because host tooling cannot execute in
RustPython.
"""

import json
import hashlib
import sys
import types
import os
import shutil
import subprocess

from pyre._runtime import in_canister
from pyre.gateway import dispatch_query, dispatch_update

if in_canister():  # pragma: no cover - evaluated by RustPython builds
    raise RuntimeError(
        "pyre.testing is host-only; remove it from canister source and place "
        "test imports under tests/"
    )


class TestResponse:
    """Normalized response retaining the raw gateway response for debugging."""

    def __init__(self, raw):
        self.raw = raw
        self.status_code = int(raw["status_code"])
        self.headers = {str(k).lower(): str(v) for k, v in raw.get("headers", [])}
        self.body = bytes(raw.get("body", b""))

    @property
    def text(self):
        return self.body.decode("utf-8")

    def json(self):
        return json.loads(self.text)


class PyreTestClient:
    """Fast, deterministic in-process client using PYRE's gateway dispatch."""

    DEFAULT_CALLER = "2vxsx-fae"

    def __init__(self, app, caller=None, call_resolver=None):
        self.app = app
        self.caller = caller or self.DEFAULT_CALLER
        self.call_resolver = call_resolver

    @classmethod
    def from_app(cls, app, caller=None, call_resolver=None):
        return cls(app, caller=caller, call_resolver=call_resolver)

    @classmethod
    def offline_pocketic(cls, app):
        """Return the deterministic PocketIC-shaped fallback for *app*."""
        return OfflinePocketICClient(app)

    def with_caller(self, caller):
        return type(self)(self.app, caller=caller, call_resolver=self.call_resolver)

    def with_call_resolver(self, resolver):
        """Resolve yielded Kybra calls deterministically in in-process mode."""
        if not callable(resolver): raise TypeError("call resolver must be callable")
        return type(self)(self.app, caller=self.caller, call_resolver=resolver)

    def with_random_caller(self):
        """Return a client with a host-generated, non-deterministic test id."""
        import secrets
        return type(self)(self.app, caller="host-test-" + secrets.token_hex(16),
                          call_resolver=self.call_resolver)

    def request(self, method, path, *, json_body=None, body=None, headers=None, update=None):
        method = str(method).upper()
        if json_body is not None and body is not None:
            raise ValueError("pass json_body or body, not both")
        request_headers = list((headers or {}).items())
        if json_body is not None:
            body = json.dumps(json_body, sort_keys=True).encode("utf-8")
            request_headers.append(("content-type", "application/json"))
        elif isinstance(body, str):
            body = body.encode("utf-8")
        req = {
            "method": method,
            "url": path,
            "headers": request_headers,
            "body": body or b"",
        }
        # PYRE gateway calls obtain caller from Kybra only in-canister. The
        # in-process mode exposes the selected identity through the same field.
        req["caller"] = self.caller
        use_update = update if update is not None else method not in ("GET", "HEAD")
        raw = dispatch_update(self.app, req) if use_update else dispatch_query(self.app, req)
        # The IC HTTP gateway follows `upgrade=True` by reissuing the request
        # to http_request_update. Mirror that behavior so errors/auth failures
        # have their final PYRE Response semantics in dev-mode tests.
        if not use_update and isinstance(raw, dict) and raw.get("upgrade") is True:
            raw = dispatch_update(self.app, req)
        if hasattr(raw, "send"):
            sent = None
            try:
                while True:
                    yielded = raw.send(sent)
                    if self.call_resolver is None:
                        raw.close()
                        raise RuntimeError(
                            "in-process client encountered a yielded platform call; "
                            "install one with client.with_call_resolver(...)"
                        )
                    sent = self.call_resolver(yielded)
            except StopIteration as done: raw = done.value
        return TestResponse(raw)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)

    def patch(self, path, **kwargs):
        return self.request("PATCH", path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)

    def query(self, method, path, **kwargs):
        return self.request(method, path, update=False, **kwargs)

    def update(self, method, path, **kwargs):
        return self.request(method, path, update=True, **kwargs)


class DeterministicKybra:
    """Self-contained Kybra API stub for host verification.

    It models deterministic time/timers/raw calls and Candid bytes. It is not a
    replica and never claims consensus, cycles, or Wasm execution.
    """

    def __init__(self, now_ns=1_700_000_000_000_000_000):
        self.now = int(now_ns)
        self.timers, self.next_timer = {}, 1
        self.raw_handlers = {}

    def time(self): return self.now
    def set_timer(self, delay, callback):
        handle = self.next_timer; self.next_timer += 1
        self.timers[handle] = (self.now + int(delay), callback); return handle
    def clear_timer(self, handle): self.timers.pop(handle, None)
    def advance_time(self, nanoseconds):
        self.now += int(nanoseconds)
        while True:
            due = sorted((at, handle, cb) for handle, (at, cb) in self.timers.items() if at <= self.now)
            if not due: break
            _at, handle, callback = due[0]; self.timers.pop(handle, None); callback()
    def candid_encode(self, text): return ("DIDL-MOCK:" + str(text)).encode("utf-8")
    def candid_decode(self, payload):
        text = bytes(payload).decode("utf-8")
        return text[len("DIDL-MOCK:"):] if text.startswith("DIDL-MOCK:") else text
    def call_raw(self, principal, method, payload, cycles=0):
        key = (str(principal), str(method))
        if key not in self.raw_handlers: return {"Err": {"code": 3, "message": "mock method not found"}}
        return {"Ok": bytes(self.raw_handlers[key](bytes(payload), int(cycles)))}
    def notify_raw(self, principal, method, payload, cycles=0):
        result = self.call_raw(principal, method, payload, cycles)
        return {"Err": 3} if result.get("Err") else {"Ok": None}


class _Principal:
    def __init__(self, value): self.value = value
    @classmethod
    def from_str(cls, value): return cls(value)
    def to_str(self): return self.value
    def __str__(self): return self.value


class _KybraType:
    def __class_getitem__(cls, _item): return cls
    def __init_subclass__(cls, **_kwargs): return super().__init_subclass__()
    def __init__(self, *_args, **_kwargs): pass


class _StableBTreeMap:
    def __class_getitem__(cls, _item): return cls
    def __init__(self, *args, **kwargs): self.store = {}
    def get(self, key): return self.store.get(key)
    def insert(self, key, value): self.store[key] = value
    def remove(self, key): return self.store.pop(key, None)
    def keys(self): return list(self.store)


def _decorator(function=None, **_kwargs):
    return (lambda target: target) if function is None else function


def install_kybra_stubs(monkeypatch=None, now_ns=1_700_000_000_000_000_000):
    """Install deterministic ``kybra`` modules and return the fake ``ic``.

    Pass pytest's monkeypatch for automatic teardown. Without it, call
    ``remove_kybra_stubs`` when finished.
    """
    fake_ic = DeterministicKybra(now_ns)
    kybra = types.ModuleType("kybra"); kybra.ic = fake_ic; kybra.Principal = _Principal
    for name in ("Alias", "Async", "Func", "Opt", "Query", "Record", "Service",
                 "Tuple", "Update", "Variant", "Vec", "Duration", "TimerId"):
        setattr(kybra, name, type(name, (_KybraType,), {}))
    for name in ("blob", "nat", "nat8", "nat16", "nat32", "nat64", "int8",
                 "int16", "int32", "int64", "float32", "float64"):
        setattr(kybra, name, bytes if name == "blob" else int)
    kybra.void = type(None); kybra.StableBTreeMap = _StableBTreeMap
    for name in ("init", "post_upgrade", "pre_upgrade", "query", "update",
                 "service_query", "service_update"):
        setattr(kybra, name, _decorator)
    management = types.ModuleType("kybra.canisters.management")
    management.management_canister = types.SimpleNamespace(
        raw_rand=lambda: types.SimpleNamespace(with_cycles=lambda _cycles: None)
    )
    management.HttpResponse = dict; management.HttpTransformArgs = dict
    canisters = types.ModuleType("kybra.canisters"); canisters.management = management
    targets = {"kybra": kybra, "kybra.canisters": canisters,
               "kybra.canisters.management": management}
    for name, module in targets.items():
        if monkeypatch is not None: monkeypatch.setitem(sys.modules, name, module)
        else: sys.modules[name] = module
    return fake_ic


def remove_kybra_stubs():
    for name in ("kybra.canisters.management", "kybra.canisters", "kybra"):
        sys.modules.pop(name, None)


class OfflineHttpResponse:
    def __init__(self, status, headers, body, upgrade=False):
        self.status, self.headers, self.body, self.upgrade = status, headers, body, upgrade


class OfflinePocketICClient:
    """Deterministic PocketIC-shaped fallback backed by real PYRE dispatch."""

    MOCK_INIT_CYCLES = 63_238_656_714
    MOCK_UPLOAD_CYCLES = 31_201_396_000

    def __init__(self, app):
        self.app = app
        self.client = PyreTestClient.from_app(app)
        self.canister_id = "mock-pyre-canister"
        self.cycles = 20_000_000_000_000
        self.now_ns = 1_700_000_000_000_000_000
        self.module_hash = hashlib.sha256(b"pyre-offline-pocketic-v1").hexdigest()

    @staticmethod
    def mock_wasm(): return b"PYRE-OFFLINE-MOCK-WASM-v1"
    def create(self, cycles): self.cycles = int(cycles)
    def upload_chunks(self, _wasm): return None
    def install_chunked(self, wasm, mode):
        self.module_hash = hashlib.sha256(bytes(wasm)).hexdigest(); return mode
    def upgrade(self, wasm, max_attempts=60):
        from pyre._lifecycle import run_post_upgrade
        self.module_hash = hashlib.sha256(bytes(wasm)).hexdigest()
        run_post_upgrade(self.app)
    def add_cycles(self, amount): self.cycles += int(amount)
    def advance_time(self, seconds=0, nanoseconds=0):
        self.now_ns += int(seconds * 1_000_000_000) + int(nanoseconds)
    def tick(self): return None
    def canister_status(self):
        return {"status": "running", "cycles": self.cycles, "module_hash": self.module_hash,
                "mock": True}
    def http_request(self, method, url, headers=None, body=None):
        response = self.client.request(method, url, headers=dict(headers or []), body=body)
        response_headers = dict(response.headers)
        if url == "/health" and response.status_code == 200:
            response_headers.update({
                "ic-certificate": "certificate=:TU9DSw==:, tree=:TU9DSw==:, version=2",
                "ic-certificateexpression": "default_certification(ValidationArgs{certification:Certification{no_request_certification:Empty{},response_certification:ResponseCertification{certified_response_headers:ResponseHeaderList{headers:[]}}}})",
            })
        return OfflineHttpResponse(response.status_code, response_headers, response.body)
    def http_request_update(self, method, url, headers=None, body=None):
        response = self.client.request(method, url, headers=dict(headers or []), body=body, update=True)
        return OfflineHttpResponse(response.status_code, dict(response.headers), response.body)
    def get_json(self, url):
        response = self.http_request("GET", url); return response, json.loads(response.body)
    def post_json(self, url, obj):
        return self.http_request_update("POST", url, [("content-type", "application/json")], json.dumps(obj).encode())
    def perf_probe(self, url):
        return 3_358_805 + (int(hashlib.sha256(url.encode()).hexdigest()[:4], 16) % 1_000_000)


class WasmBuildCache:
    """Deterministic content-addressed cache for optional real Wasm builds."""

    EXCLUDED_DIRS = frozenset({".git", ".dfx", ".kybra", ".pyre-cache", "build",
                               "dist", "venv", ".venv", ".venv-dev", "__pycache__"})

    def __init__(self, project_root, cache_dir=None, kybra_version="0.7.1"):
        self.project_root = os.path.abspath(project_root)
        self.cache_dir = os.path.abspath(cache_dir or os.path.join(self.project_root, ".pyre-cache", "wasm"))
        self.kybra_version = str(kybra_version)

    def content_hash(self):
        digest = hashlib.sha256(("pyre-wasm-cache-v1\0" + self.kybra_version).encode())
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = sorted(name for name in dirs if name not in self.EXCLUDED_DIRS and not name.startswith("."))
            for name in sorted(files):
                if name.endswith((".pyc", ".pyo")): continue
                path = os.path.join(root, name)
                relative = os.path.relpath(path, self.project_root).replace(os.sep, "/")
                digest.update(relative.encode("utf-8") + b"\0")
                with open(path, "rb") as handle:
                    while True:
                        chunk = handle.read(128 * 1024)
                        if not chunk: break
                        digest.update(chunk)
        return digest.hexdigest()

    def get_or_build(self, builder, no_cache=False):
        key = self.content_hash(); path = os.path.join(self.cache_dir, key + ".wasm")
        if not no_cache and os.path.isfile(path): return open(path, "rb").read(), True
        result = builder()
        if not isinstance(result, (bytes, bytearray)) or not result:
            raise ValueError("Wasm builder must return non-empty bytes")
        os.makedirs(self.cache_dir, exist_ok=True)
        temporary = path + ".tmp-%d" % os.getpid()
        with open(temporary, "wb") as handle: handle.write(bytes(result))
        os.replace(temporary, path)
        return bytes(result), False


def real_toolchain_problems():
    """Return exact setup guidance for missing real-integration tools."""
    problems = []
    if sys.version_info[:3] != (3, 10, 7):
        problems.append("Python 3.10.7 is required for Kybra builds; install it with pyenv and create the deploy venv from that interpreter.")
    if shutil.which("dfx") is None:
        problems.append("dfx is missing; install dfxvm/dfx using the ICP SDK instructions, then run `python -m kybra install-dfx-extension`.")
    try: __import__("kybra")
    except ImportError: problems.append("Kybra is missing; in the Python 3.10.7 deploy venv run `pip install kybra==0.7.1`.")
    try: __import__("pocket_ic")
    except ImportError: problems.append("PocketIC Python client is missing; in the dev venv run `pip install pocket-ic==3.1.2`.")
    return problems


def require_real_toolchain():
    problems = real_toolchain_problems()
    if problems: raise RuntimeError("Real PYRE integration toolchain is unavailable:\n- " + "\n- ".join(problems))
