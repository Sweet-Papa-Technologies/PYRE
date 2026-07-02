"""PocketIC integration-test fixtures (v1.1 Phase 0).

These tests boot a real PocketIC server (a lightweight IC replica) and
exercise the prebuilt Kybra wasm artifacts end to end: install, HTTP
gateway queries/updates, certification headers, upgrades, and cycle/
instruction measurement.

Skip behaviour: the whole directory is skipped unless a PocketIC server
binary is found (POCKET_IC_BIN, or the pinned version in the cache
populated by scripts/pocketic_setup.sh) AND the prebuilt rest_api wasm
exists. The plain unit suite stays fast and dependency-free.

Version pins (keep in lockstep, see scripts/pocketic_setup.sh):
    pip: pocket-ic==3.1.2 (pulls ic-py)
    server: PocketIC 13.0.0
"""

import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest

POCKET_IC_SERVER_VERSION = "13.0.0"
REPO_ROOT = Path(__file__).resolve().parents[2]

# Prefer the dfx-gzipped artifact (half the bytes to upload); fall back to
# gzipping the raw Kybra artifact in memory.
REST_API_WASM_GZ = REPO_ROOT / ".dfx/local/canisters/rest_api/rest_api.wasm.gz"
REST_API_WASM = REPO_ROOT / ".kybra/rest_api/rest_api.wasm"

EMPTY_CANDID_ARG = b"DIDL\x00\x00"  # zero types, zero values — no init args
CHUNK_SIZE = 1 << 20  # management-canister chunk store limit is 1 MiB

# Session-level measurements, filled by fixtures/tests and echoed in the
# terminal summary so budget numbers are visible in every run.
METRICS: dict = {}


def _find_pocket_ic_bin():
    env = os.environ.get("POCKET_IC_BIN")
    if env and os.path.isfile(env):
        return env
    cached = (
        Path.home() / ".cache" / "pocket-ic" / POCKET_IC_SERVER_VERSION / "pocket-ic"
    )
    if cached.is_file():
        return str(cached)
    return None


@pytest.fixture(scope="session")
def metrics():
    """Session-wide measurement dict, echoed in the terminal summary."""
    return METRICS


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "pocketic: integration tests that need a PocketIC server binary"
    )


def pytest_collection_modifyitems(config, items):
    if _find_pocket_ic_bin():
        return
    skip = pytest.mark.skip(
        reason="PocketIC server binary not found; set POCKET_IC_BIN or run "
        "scripts/pocketic_setup.sh"
    )
    this_dir = str(Path(__file__).parent)
    for item in items:
        if str(item.fspath).startswith(this_dir):
            item.add_marker(skip)


def pytest_terminal_summary(terminalreporter):
    if not METRICS:
        return
    terminalreporter.section("PocketIC measurements")
    for key, value in METRICS.items():
        terminalreporter.write_line(
            f"{key}: {value:,}" if isinstance(value, int) else f"{key}: {value}"
        )


# --------------------------------------------------------------------------
# Everything below imports pocket_ic/ic lazily so collection never fails in
# environments without the integration-test dependencies installed.
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pic():
    """A PocketIC instance with one application subnet."""
    bin_path = _find_pocket_ic_bin()
    if bin_path is None:
        pytest.skip("PocketIC server binary not found")
    pocket_ic = pytest.importorskip("pocket_ic")

    os.environ["POCKET_IC_BIN"] = bin_path
    os.environ.setdefault("POCKET_IC_MUTE_SERVER", "1")
    # Skip macOS system proxy lookups in requests: faster, and avoids noisy
    # "sys.meta_path is None" ImportErrors from PocketIC.__del__ at shutdown.
    os.environ.setdefault("NO_PROXY", "*")
    os.environ.setdefault("no_proxy", "*")

    instance = pocket_ic.PocketIC()
    yield instance
    # Explicit teardown: __del__ during interpreter shutdown raises noisy
    # ImportErrors from requests, so delete the instance while alive.
    instance.server.delete_instance(instance.instance_id)


@pytest.fixture(scope="session")
def rest_api_wasm_gz():
    if REST_API_WASM_GZ.is_file():
        return REST_API_WASM_GZ.read_bytes()
    if REST_API_WASM.is_file():
        return gzip.compress(REST_API_WASM.read_bytes(), 6)
    pytest.skip(
        "prebuilt rest_api wasm not found (.dfx/local/canisters/rest_api/"
        "rest_api.wasm.gz or .kybra/rest_api/rest_api.wasm) — build it first"
    )


@pytest.fixture(scope="session")
def rest_api(pic, rest_api_wasm_gz):
    """The rest_api example canister, installed and ready, plus install metrics."""
    client = PyreCanisterClient(pic)
    client.create(cycles=20_000_000_000_000)  # Kybra init is instruction-heavy
    balance_before = pic.get_cycles_balance(client.canister_id)
    client.upload_chunks(rest_api_wasm_gz)
    balance_after_upload = pic.get_cycles_balance(client.canister_id)
    client.install_chunked(rest_api_wasm_gz, mode="install")
    balance_after_install = pic.get_cycles_balance(client.canister_id)

    METRICS["install (init) cycles consumed"] = (
        balance_after_upload - balance_after_install
    )
    METRICS["chunk upload cycles consumed"] = balance_before - balance_after_upload
    return client


class PyreCanisterClient:
    """Thin candid wrapper for the PYRE HTTP-gateway interface on PocketIC."""

    def __init__(self, pic):
        from ic.candid import Types

        self.pic = pic
        self.canister_id = None
        self._blob = _make_blob_type()

        self.request_type = Types.Record(
            {
                "method": Types.Text,
                "url": Types.Text,
                "headers": Types.Vec(Types.Tuple(Types.Text, Types.Text)),
                "body": self._blob,
            }
        )
        token = Types.Record({"arbitrary_data": Types.Text})
        callback_ret = Types.Record({"token": Types.Opt(token), "body": self._blob})
        self.response_type = Types.Record(
            {
                "status_code": Types.Nat16,
                "headers": Types.Vec(Types.Tuple(Types.Text, Types.Text)),
                "body": self._blob,
                "streaming_strategy": Types.Opt(
                    Types.Variant(
                        {
                            "Callback": Types.Record(
                                {
                                    "callback": Types.Func(
                                        [token], [callback_ret], ["query"]
                                    ),
                                    "token": token,
                                }
                            )
                        }
                    )
                ),
                "upgrade": Types.Opt(Types.Bool),
            }
        )

    # -- lifecycle ---------------------------------------------------------

    def create(self, cycles):
        self.canister_id = self.pic.create_canister()
        self.pic.add_cycles(self.canister_id, cycles)

    def _mgmt_call(self, method, payload):
        import base64

        return self.pic.update_call_with_effective_principal(
            None,
            {"CanisterId": base64.b64encode(self.canister_id.bytes).decode()},
            method,
            payload,
        )

    def upload_chunks(self, wasm):
        """Store the wasm in the canister's chunk store, 1 MiB at a time.

        Kybra modules are far beyond PocketIC's enforced 2 MiB ingress limit,
        so a plain install_code ingress message is rejected; chunked install
        is required.
        """
        from ic.candid import Types, encode

        upload_arg = Types.Record(
            {"canister_id": Types.Principal, "chunk": self._blob}
        )
        for start in range(0, len(wasm), CHUNK_SIZE):
            chunk = wasm[start : start + CHUNK_SIZE]
            payload = encode(
                [
                    {
                        "type": upload_arg,
                        "value": {
                            "canister_id": self.canister_id.bytes,
                            "chunk": chunk,
                        },
                    }
                ]
            )
            self._mgmt_call("upload_chunk", payload)

    def install_chunked(self, wasm, mode):
        """install_chunked_code from previously uploaded chunks."""
        from ic.candid import Types, encode

        hashes = [
            hashlib.sha256(wasm[start : start + CHUNK_SIZE]).digest()
            for start in range(0, len(wasm), CHUNK_SIZE)
        ]
        install_arg = Types.Record(
            {
                "mode": Types.Variant(
                    {
                        "install": Types.Null,
                        "reinstall": Types.Null,
                        "upgrade": Types.Null,
                    }
                ),
                "target_canister": Types.Principal,
                "store_canister": Types.Opt(Types.Principal),
                "chunk_hashes_list": Types.Vec(Types.Record({"hash": self._blob})),
                "wasm_module_hash": self._blob,
                "arg": self._blob,
                "sender_canister_version": Types.Opt(Types.Nat64),
            }
        )
        payload = encode(
            [
                {
                    "type": install_arg,
                    "value": {
                        "mode": {mode: None},
                        "target_canister": self.canister_id.bytes,
                        "store_canister": [],
                        "chunk_hashes_list": [{"hash": h} for h in hashes],
                        "wasm_module_hash": hashlib.sha256(wasm).digest(),
                        "arg": EMPTY_CANDID_ARG,
                        "sender_canister_version": [],
                    },
                }
            ]
        )
        self._mgmt_call("install_chunked_code", payload)

    def upgrade(self, wasm, max_attempts=60):
        """Upgrade-mode reinstall; chunks persist in the store from install.

        Kybra installs are so instruction-heavy that the replica's
        install_code rate limiter (CanisterInstallCodeRateLimited) usually
        rejects an immediate second install; the allowance replenishes per
        round, so tick/advance time and retry.
        """
        for attempt in range(max_attempts):
            try:
                self.install_chunked(wasm, mode="upgrade")
                return
            except (ValueError, ConnectionError) as error:
                if "rate limited" not in str(error).lower():
                    raise
                self.pic.advance_time(60 * 1_000_000_000)  # +60 s
                self.pic.tick()
        raise TimeoutError(
            f"install_chunked_code still rate limited after {max_attempts} retries"
        )

    # -- HTTP gateway ------------------------------------------------------

    def _encode_request(self, method, url, headers, body):
        from ic.candid import encode

        return encode(
            [
                {
                    "type": self.request_type,
                    "value": {
                        "method": method,
                        "url": url,
                        "headers": headers or [],
                        "body": body or b"",
                    },
                }
            ]
        )

    def _decode_response(self, raw):
        from ic.candid import decode

        value = decode(bytes(raw), self.response_type)[0]["value"]
        upgrade = value["upgrade"]  # ic-py decodes opt as [] / [value]
        return HttpResponse(
            status=value["status_code"],
            headers={name.lower(): val for name, val in value["headers"]},
            body=bytes(value["body"]),
            upgrade=bool(upgrade and upgrade[0]),
        )

    def http_request(self, method, url, headers=None, body=None):
        raw = self.pic.query_call(
            self.canister_id,
            "http_request",
            self._encode_request(method, url, headers, body),
        )
        response = self._decode_response(raw)
        if response.upgrade:
            # Mimic the HTTP gateway's upgrade-to-update flow: PYRE answers
            # 204 + upgrade=true for responses it can't serve certified from
            # the query path (e.g. 404s), and the gateway re-issues the same
            # request as an update call.
            return self.http_request_update(method, url, headers, body)
        return response

    def http_request_update(self, method, url, headers=None, body=None):
        raw = self.pic.update_call(
            self.canister_id,
            "http_request_update",
            self._encode_request(method, url, headers, body),
        )
        return self._decode_response(raw)

    def get_json(self, url):
        response = self.http_request("GET", url)
        return response, json.loads(response.body)

    def post_json(self, url, obj):
        return self.http_request_update(
            "POST",
            url,
            headers=[("content-type", "application/json")],
            body=json.dumps(obj).encode(),
        )

    def perf_probe(self, url):
        """Instruction count for one query dispatch (pyre_perf_probe)."""
        from ic.candid import Types, decode, encode

        raw = self.pic.query_call(
            self.canister_id,
            "pyre_perf_probe",
            encode([{"type": Types.Text, "value": url}]),
        )
        return decode(bytes(raw), Types.Nat64)[0]["value"]


class HttpResponse:
    def __init__(self, status, headers, body, upgrade=False):
        self.status = status
        self.headers = headers  # dict, lower-cased names
        self.body = body
        self.upgrade = upgrade


def _make_blob_type():
    """vec nat8 with O(n) bytes fast paths.

    ic-py's stock Vec(Nat8) encodes one Python call per byte, which takes
    minutes for a 14 MB Kybra wasm module; this subclass moves whole bytes
    objects in one go.
    """
    import leb128
    from ic.candid import Types, VecClass, leb128uDecode

    class BlobClass(VecClass):
        def __init__(self):
            super().__init__(Types.Nat8)

        def covariant(self, x):
            return isinstance(x, (bytes, bytearray))

        def encodeValue(self, val):
            return leb128.u.encode(len(val)) + bytes(val)

        def decodeValue(self, b, t):
            self.checkType(t)
            return b.read(leb128uDecode(b))

    return BlobClass()
