"""pyre.adapters — Supabase (PostgREST) + Upstash Redis over outcalls."""

import json

import pytest

from pyre.adapters import supabase, upstash
from pyre.errors import PyreError
from pyre.outcall import OutcallFuture, UrlResponse, pump_sync


def make_resolver(status=200, body=b"[]", headers=None, capture=None):
    def resolve(fut):
        assert isinstance(fut, OutcallFuture)
        if capture is not None:
            capture.append(fut)
        return UrlResponse(status, headers or {"content-type": "application/json"},
                           body, fut.url)
    return resolve


def run(awaitable, resolver):
    async def handler():
        return await awaitable
    return pump_sync(handler(), resolver)


# -- supabase ----------------------------------------------------------------

DB = supabase.Client(url="https://proj.supabase.co", anon_key="anon-key")


def test_select_builds_postgrest_url():
    captured = []
    rows = run(
        DB.table("items").select("id,title").eq("done", "false").order("id").limit(10),
        make_resolver(body=b'[{"id": 1}]', capture=captured),
    )
    fut = captured[0]
    assert fut.method == "GET"
    assert fut.url == (
        "https://proj.supabase.co/rest/v1/items"
        "?select=id,title&done=eq.false&order=id.asc&limit=10"
    )
    assert fut.headers["apikey"] == "anon-key"
    assert fut.headers["authorization"] == "Bearer anon-key"
    assert rows == [{"id": 1}]


def test_query_string_is_percent_encoded():
    captured = []
    run(DB.table("items").select().eq("title", "a b&c"),
        make_resolver(capture=captured))
    assert "title=eq.a%20b%26c" in captured[0].url


def test_insert_is_an_idempotent_upsert():
    captured = []
    run(DB.table("items").insert({"id": "u-1", "title": "x"}),
        make_resolver(body=b'[{"id": "u-1"}]', capture=captured))
    fut = captured[0]
    assert fut.method == "POST"
    assert json.loads(fut.data.decode()) == [{"id": "u-1", "title": "x"}]
    assert "resolution=merge-duplicates" in fut.headers["prefer"]


def test_update_requires_key_and_sets_on_conflict():
    captured = []
    run(DB.table("items").update({"id": "u-1", "title": "y"}, key="id"),
        make_resolver(body=b'[{"id": "u-1"}]', capture=captured))
    assert "on_conflict=id" in captured[0].url
    with pytest.raises(PyreError):
        DB.table("items").update({"title": "no key"}, key="id")


def test_delete_refused_with_rpc_hint():
    with pytest.raises(PyreError) as exc:
        DB.table("items").delete()
    assert "rpc" in str(exc.value)


def test_rpc_posts_args():
    captured = []
    run(DB.rpc("delete_item", {"item_id": "u-1"}),
        make_resolver(body=b"null", capture=captured))
    fut = captured[0]
    assert fut.url.endswith("/rest/v1/rpc/delete_item")
    assert json.loads(fut.data.decode()) == {"item_id": "u-1"}


def test_single_unwraps_and_enforces_one_row():
    row = run(DB.table("items").select().eq("id", "1").single(),
              make_resolver(body=b'[{"id": "1"}]'))
    assert row == {"id": "1"}
    with pytest.raises(supabase.SupabaseError):
        run(DB.table("items").select().single(),
            make_resolver(body=b'[{"id": "1"}, {"id": "2"}]'))


def test_postgrest_error_maps_to_supabase_error():
    with pytest.raises(supabase.SupabaseError) as exc:
        run(DB.table("items").select(),
            make_resolver(status=401, body=b'{"message": "JWT expired"}'))
    assert exc.value.http_status == 401
    assert "JWT expired" in str(exc.value)


def test_generator_style_handler_works():
    def handler():
        rows = yield from DB.table("items").select()
        return rows
    assert pump_sync(handler(), make_resolver(body=b"[]")) == []


# -- upstash -----------------------------------------------------------------

REDIS = upstash.Client(url="https://db.upstash.io", token="tok")


def test_command_posts_json_array_with_bearer():
    captured = []
    result = run(REDIS.set("k", "v", ex=60),
                 make_resolver(body=b'{"result": "OK"}', capture=captured))
    fut = captured[0]
    assert result == "OK"
    assert fut.method == "POST"
    assert fut.url == "https://db.upstash.io"
    assert fut.headers["authorization"] == "Bearer tok"
    assert json.loads(fut.data.decode()) == ["SET", "k", "v", "EX", "60"]


def test_non_idempotent_commands_refused():
    with pytest.raises(upstash.UpstashError) as exc:
        REDIS.command("INCR", "hits")
    assert "idempotent" in str(exc.value)
    captured = []
    run(REDIS.command("INCR", "hits", unsafe_amplified=True),
        make_resolver(body=b'{"result": 13}', capture=captured))
    assert json.loads(captured[0].data.decode()) == ["INCR", "hits"]


def test_upstash_error_payload_raises():
    with pytest.raises(upstash.UpstashError) as exc:
        run(REDIS.get("k"),
            make_resolver(status=401, body=b'{"error": "invalid token"}'))
    assert "invalid token" in str(exc.value)


def test_get_returns_result_field():
    assert run(REDIS.get("k"), make_resolver(body=b'{"result": "42"}')) == "42"


def test_hset_flattens_mapping():
    captured = []
    run(REDIS.hset("h", {"a": "1", "b": "2"}),
        make_resolver(body=b'{"result": 2}', capture=captured))
    parts = json.loads(captured[0].data.decode())
    assert parts[0] == "HSET" and parts[1] == "h"
    assert set(zip(parts[2::2], parts[3::2])) == {("a", "1"), ("b", "2")}
