"""Deterministic, network-free E2E fallback over real PYRE dispatch/state."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "examples/rest_api/src"
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(SRC))

from pyre import kv
from pyre.testing import OfflinePocketICClient

kv._backend = kv._DevBackend()
spec = importlib.util.spec_from_file_location("__pyre_offline_e2e_app__", SRC / "app.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
client = OfflinePocketICClient(module.app)
wasm = client.mock_wasm(); client.install_chunked(wasm, "install")

response, payload = client.get_json("/health")
assert response.status == 200 and payload == {"status": "ok"}
assert "ic-certificate" in response.headers
response, payload = client.get_json("/echo/offline")
assert response.status == 200 and payload == {"hello": "offline"}
item = {"id": "offline-1", "name": "deterministic"}
assert client.post_json("/items", item).status == 201
client.upgrade(wasm)
response, payload = client.get_json("/items/offline-1")
assert response.status == 200 and payload == item
assert client.http_request("GET", "/missing").status == 404
print("PASS  offline routing, certification wiring, update persistence, upgrade, and errors")
print("NOTE  fallback does not claim Wasm execution, replica consensus, BLS verification, or real cycles")
