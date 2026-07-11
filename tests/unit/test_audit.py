import json
import importlib.metadata

from pyre import cli
from pyre._audit import run
from pyre import _audit


def test_audit_is_deterministic_and_detects_host_import_and_footgun(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("import pytest\nimport random\n", encoding="utf-8")
    first, code = run(canister=str(tmp_path))
    second, _ = run(canister=str(tmp_path))
    assert first == second
    assert code == 2
    assert {item["code"] for item in first["findings"]} == {
        "PYRE-AUDIT-HOST-TOOL-IMPORT", "PYRE-AUDIT-NONDETERMINISM"
    }


def test_unknown_unpinned_requirement_is_warning_and_strict_exit_one(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("mystery-package>=1\n", encoding="utf-8")
    report, code = run(requirements=str(requirements), strict=False)
    assert report["status"] == "pass"
    assert code == 0
    strict_report, strict_code = run(requirements=str(requirements), strict=True)
    assert strict_report["status"] == "fail"
    assert strict_code == 1
    assert "PYRE-AUDIT-UNKNOWN-PACKAGE" in {item["code"] for item in report["findings"]}


def test_pinned_unknown_is_not_silently_labeled_compatible(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("never-tested-package==1.0\n", encoding="utf-8")
    report, code = run(requirements=str(requirements))
    assert code == 0
    finding = next(item for item in report["findings"] if item["code"] == "PYRE-AUDIT-UNKNOWN-PACKAGE")
    assert finding["package"] == "never-tested-package"


def test_native_source_rustpython_gap_and_secret_heuristic(tmp_path):
    (tmp_path / "app.py").write_text('import socket\nAPI_TOKEN = "plaintext"\n', encoding="utf-8")
    (tmp_path / "extension.so").write_bytes(b"native")
    report, code = run(canister=str(tmp_path))
    assert code == 2
    codes = {item["code"] for item in report["findings"]}
    assert {"PYRE-AUDIT-RUSTPYTHON-GAP", "PYRE-AUDIT-PLAINTEXT-SECRET",
            "PYRE-AUDIT-NATIVE-EXTENSION"} <= codes


def test_installed_distribution_metadata_is_inspected_without_import(monkeypatch, tmp_path):
    class Distribution:
        files = ["native_pkg/__init__.py", "native_pkg/_core.so"]
        def read_text(self, name):
            assert name == "WHEEL"
            return "Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp310-macosx\n"

    imported = []
    monkeypatch.setattr(importlib.metadata, "distribution", lambda name: Distribution())
    builtins = __import__("builtins")
    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__",
                        lambda name, *a, **kw: imported.append(name) or (_ for _ in ()).throw(AssertionError("package code imported"))
                        if name == "native-pkg" else real_import(name, *a, **kw))
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("native-pkg==1.0\n", encoding="utf-8")
    report, code = run(requirements=str(requirements))
    assert code == 2 and imported == []
    codes = {item["code"] for item in report["findings"]}
    assert {"PYRE-AUDIT-NATIVE-EXTENSION", "PYRE-AUDIT-NON-PURE-WHEEL",
            "PYRE-AUDIT-UNKNOWN-PACKAGE"} <= codes


def test_cli_json_schema_and_exit_code(tmp_path, capsys):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("thing\n", encoding="utf-8")
    assert cli.main(["audit", str(requirements), "--format", "json", "--strict"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == 1
    assert set(payload) == {"schema", "status", "environment", "findings"}


def test_cli_missing_explicit_paths_are_configuration_errors(tmp_path, capsys):
    assert cli.main(["audit", str(tmp_path / "missing.txt")]) == 3
    assert "does not exist" in capsys.readouterr().err
    assert cli.main(["audit", "--canister", str(tmp_path / "missing-src")]) == 3
