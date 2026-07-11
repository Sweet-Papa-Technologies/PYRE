from pyre import cli


def test_list_verify_and_batched_delete_cli(monkeypatch, capsys):
    replies = {
        "/list": {"assets": [{"asset_id": "a", "size": 3, "sha256": "abc"}]},
        "/verify": {"asset_id": "a", "ok": True, "size": 3, "sha256": "abc"},
    }
    delete_calls = []

    def fake_call(args, endpoint, payload=None):
        if endpoint == "/delete":
            delete_calls.append(payload)
            return ({"removed_chunks": 1, "complete": len(delete_calls) == 2}, 0)
        return replies[endpoint], 0

    monkeypatch.setattr(cli, "_asset_management_call", fake_call)
    common = ["--url", "http://example", "--token", "token"]
    assert cli.main(["assets", "list"] + common) == 0
    assert cli.main(["assets", "verify", "a"] + common) == 0
    assert cli.main(["assets", "delete", "a", "--batch-size", "1"] + common) == 0
    output = capsys.readouterr().out
    assert "1 asset(s)" in output and "verified" in output and "2 chunk(s)" in output
    assert len(delete_calls) == 2


def test_generalized_single_file_push_reports_required_metrics(monkeypatch, tmp_path, capsys):
    source = tmp_path / "movie.mp4"; source.write_bytes(b"x" * 1500)
    chunks = []

    def fake_push(method, url, token, payload, connect=None, **_kwargs):
        if url.endswith("/manifest"):
            return 200, {"chunk_size": 1024, "present": [], "session": {
                "session_id": "session", "chunks": 2,
            }}
        if url.endswith("/chunk"):
            chunks.append(payload); return 200, {"ok": True}
        if url.endswith("/finalize"):
            return 200, {"asset": {"asset_id": "movie.mp4"}}
        raise AssertionError(url)

    monkeypatch.setattr(cli, "_push_call", fake_push)
    args = type("Args", (), {"dist": str(source), "namespace": "media",
        "asset_id": None, "url": "http://example", "admin_prefix": None,
        "token": "secret", "connect": None})()
    assert cli.cmd_assets_push(args) == 0
    output = capsys.readouterr().out
    assert "uploaded_bytes=1500" in output and "wire_bytes=1500" in output
    assert "chunks=2" in output and "sha256=" in output and "asset_id=movie.mp4" in output
    assert len(chunks) == 2
