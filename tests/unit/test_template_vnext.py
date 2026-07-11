from pathlib import Path


def test_all_templates_use_lifecycle_and_declare_streaming_callback():
    root = Path(__file__).resolve().parents[2] / "pyre" / "templates"
    for main in sorted(root.glob("*/src/main.py")):
        source = main.read_text()
        assert "run_init(app)" in source
        assert "run_post_upgrade(app)" in source
        assert "def pyre_http_streaming_callback" in source
        assert '(ic.id(), "pyre_http_streaming_callback")' in source
