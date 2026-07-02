"""pyre.log — logging surface (WS-E leftover, shipped in v1.1)."""

import pytest

from pyre import log


@pytest.fixture(autouse=True)
def reset_level():
    log.set_level("debug")
    yield
    log.set_level("debug")


def capture(monkeypatch):
    lines = []
    monkeypatch.setattr(log, "_print", lines.append)
    return lines


def test_levels_and_structured_fields(monkeypatch):
    lines = capture(monkeypatch)
    log.info("item created", id="i-1", n=3)
    assert lines == ['[INFO] item created {"id": "i-1", "n": 3}']


def test_level_gating(monkeypatch):
    lines = capture(monkeypatch)
    log.set_level("warning")
    log.debug("noise")
    log.info("noise")
    log.warning("kept")
    log.error("kept too")
    assert [l.split("]")[0] for l in lines] == ["[WARNING", "[ERROR"]


def test_exception_helper(monkeypatch):
    lines = capture(monkeypatch)
    try:
        raise ValueError("boom")
    except ValueError as e:
        log.exception("handler failed", e, route="/items")
    assert "ValueError" in lines[0] and "boom" in lines[0] and "/items" in lines[0]


def test_unserializable_fields_fall_back_to_repr(monkeypatch):
    lines = capture(monkeypatch)

    class Weird:
        def __repr__(self):
            return "<weird>"

    log.info("msg", obj=Weird())
    assert "weird" in lines[0]


def test_dev_fallback_prints_to_stderr(capsys):
    log.info("dev line", k="v")
    assert "dev line" in capsys.readouterr().err
