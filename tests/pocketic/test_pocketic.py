"""PocketIC integration tests for the rest_api example canister (v1.1 Phase 0).

Covers: HTTP gateway query/update dispatch, state persistence, certification
wiring, upgrade survival, and init/per-request budget measurement against the
prebuilt Kybra artifacts. See conftest.py for fixtures and skip logic.
"""

import pytest

pytestmark = pytest.mark.pocketic

# Budget thresholds: actuals measured 2026-07-02 on PocketIC 13.0.0 with the
# v1.0 artifacts, plus ~25% headroom. See scratchpad pocketic-notes.md.
#   install (init) cycles consumed: 63,238,656,714
#   chunk upload cycles consumed:   31,201,396,000
#   pyre_perf_probe /health:         3,358,805 instructions
#   pyre_perf_probe /echo/{name}:    4,163,633 instructions
#   pyre_perf_probe /items/{id}:     4,950,803-6,019,682 instructions
#     (varies with kv size: probe runs after the upgrade test adds an item)
INIT_CYCLES_THRESHOLD = 80_000_000_000
QUERY_INSTRUCTIONS_THRESHOLD = 7_500_000


# --- http_request (query path) ---------------------------------------------


def test_health_query(rest_api):
    response, payload = rest_api.get_json("/health")
    assert response.status == 200
    assert payload == {"status": "ok"}


def test_unknown_route_is_404(rest_api):
    response = rest_api.http_request("GET", "/definitely-not-a-route")
    assert response.status == 404


def test_path_params_route(rest_api):
    response, payload = rest_api.get_json("/echo/pocketic")
    assert response.status == 200
    assert payload == {"hello": "pocketic"}


# --- certification wiring ----------------------------------------------------


def test_certified_route_has_ic_certificate_header(rest_api):
    """PocketIC subnets have a real root key, so the certified /health route
    must carry v2 response-certification headers. Full BLS verification is
    covered by scripts/verify_certification.py; here we assert the wiring."""
    response = rest_api.http_request("GET", "/health")
    assert response.status == 200
    assert "ic-certificate" in response.headers
    certificate = response.headers["ic-certificate"]
    assert "certificate=:" in certificate
    assert "tree=:" in certificate
    assert "version=2" in certificate
    assert "ic-certificateexpression" in response.headers


# --- http_request_update (update path) + persistence -------------------------


def test_post_then_get_persists(rest_api):
    item = {"id": "pic-1", "name": "pocketic smoke item"}
    response = rest_api.post_json("/items", item)
    assert response.status == 201

    response, payload = rest_api.get_json("/items/pic-1")
    assert response.status == 200
    assert payload == item


# --- upgrade survival ---------------------------------------------------------


def test_kv_survives_upgrade(rest_api, rest_api_wasm_gz):
    item = {"id": "pre-upgrade", "name": "written before upgrade"}
    assert rest_api.post_json("/items", item).status == 201

    # Upgrade-mode reinstall with the same wasm (chunks persist in the
    # canister's chunk store from the initial install).
    rest_api.upgrade(rest_api_wasm_gz)

    response, payload = rest_api.get_json("/items/pre-upgrade")
    assert response.status == 200
    assert payload == item

    # Post-upgrade recertification hook ran: certified route still wired.
    response = rest_api.http_request("GET", "/health")
    assert response.status == 200
    assert "ic-certificate" in response.headers


# --- budgets: init cycles + per-request instructions --------------------------


def test_init_cycles_within_budget(rest_api, metrics):
    """Kybra init boots a whole Python interpreter; the cycle-balance delta
    across install_chunked_code is our proxy for init instructions (the
    pocket-ic 3.1.2 Python API exposes no per-message instruction counts)."""
    init_cycles = metrics["install (init) cycles consumed"]
    print(f"\ninstall (init) cycles consumed: {init_cycles:,}")
    assert 0 < init_cycles < INIT_CYCLES_THRESHOLD


def test_per_request_instructions_within_budget(rest_api, metrics):
    for url in ("/health", "/echo/pocketic", "/items/pic-1"):
        instructions = rest_api.perf_probe(url)
        metrics[f"pyre_perf_probe {url} instructions"] = instructions
        print(f"\npyre_perf_probe {url}: {instructions:,} instructions")
        assert 0 < instructions < QUERY_INSTRUCTIONS_THRESHOLD
