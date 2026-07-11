"""Offline compatibility audit used by ``pyre audit``."""

import ast
import os
import platform
import re
import importlib.metadata

from pyre import __version__
from pyre.cli import RESERVED_BASENAMES, check_footguns

SCHEMA = 1
COMPATIBILITY_SCHEMA = 1
HOST_ONLY_IMPORTS = {"pytest", "pocket_ic", "setuptools", "wheel", "pip"}
NATIVE_SUFFIXES = (".so", ".pyd", ".dylib", ".dll")
RUSTPYTHON_GAPS = {"socket", "multiprocessing", "threading", "sqlite3", "tkinter"}
COMPATIBILITY = {
    "pyre-icp": ("compatible", "tested with PYRE 1.2.1 / Kybra 0.7.1"),
    "kybra": ("compatible", "Kybra 0.7.1 is the pinned CDK"),
    "numpy": ("incompatible", "native extension dependency; no supported RustPython Wasm path"),
    "pandas": ("incompatible", "native NumPy dependency; no supported RustPython Wasm path"),
    "pytest": ("incompatible", "host-only test tool"),
    "pocket-ic": ("incompatible", "host-only test tool"),
}
_SECRET_NAMES = ("password", "passwd", "secret", "token", "api_key", "apikey", "private_key")


def _finding(code, severity, evidence, remediation, package=None):
    item = {
        "code": code,
        "severity": severity,
        "evidence": str(evidence)[:1000],
        "remediation": remediation,
    }
    if package:
        item["package"] = package
    return item


def _python_files(path):
    if os.path.isfile(path):
        return [path] if path.endswith(".py") else []
    found = []
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in {".git", "venv", ".venv", "site-packages", "__pycache__"})
        found.extend(os.path.join(root, name) for name in sorted(files) if name.endswith(".py"))
    return found


def audit_canister(path):
    findings = []
    base = path if os.path.isdir(path) else os.path.dirname(path) or "."
    for filename in _python_files(path):
        stem = os.path.splitext(os.path.basename(filename))[0]
        if stem in RESERVED_BASENAMES:
            findings.append(_finding(
                "PYRE-AUDIT-RESERVED-BASENAME", "error", filename,
                "Rename the module; Kybra flattens module basenames during bundling.",
            ))
        try:
            source = open(filename, encoding="utf-8").read()
            tree = ast.parse(source, filename)
        except (OSError, SyntaxError) as exc:
            findings.append(_finding("PYRE-AUDIT-SOURCE", "error", exc, "Fix the unreadable or invalid Python source."))
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".", 1)[0]]
            for name in names:
                if name in HOST_ONLY_IMPORTS:
                    findings.append(_finding(
                        "PYRE-AUDIT-HOST-TOOL-IMPORT", "error",
                        "%s:%d imports %s" % (filename, node.lineno, name),
                        "Move host-only imports into the test or build environment.", package=name,
                    ))
                if name in RUSTPYTHON_GAPS:
                    findings.append(_finding(
                        "PYRE-AUDIT-RUSTPYTHON-GAP", "error",
                        "%s:%d imports %s" % (filename, node.lineno, name),
                        "Remove the unsupported runtime module or isolate it in host-only tooling.", package=name,
                    ))
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                names = [target.id for target in targets if isinstance(target, ast.Name)]
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:
                    for name in names:
                        if any(marker in name.lower() for marker in _SECRET_NAMES):
                            findings.append(_finding(
                                "PYRE-AUDIT-PLAINTEXT-SECRET", "warning",
                                "%s:%d assigns a string literal to %s" % (filename, node.lineno, name),
                                "Load deployment configuration without persisting/logging plaintext, or store a one-way hash where applicable.",
                            ))
    if os.path.isdir(base):
        for root, _dirs, files in os.walk(base):
            for name in sorted(files):
                if name.lower().endswith(NATIVE_SUFFIXES):
                    findings.append(_finding(
                        "PYRE-AUDIT-NATIVE-EXTENSION", "error", os.path.join(root, name),
                        "Remove native host binaries from canister source; use a reviewed Kybra/Rust extension path.",
                    ))
    for filename, lineno, message in check_footguns(base):
        findings.append(_finding(
            "PYRE-AUDIT-NONDETERMINISM", "error", "%s:%d" % (filename, lineno), message,
        ))
    return findings


def audit_requirements(path):
    findings = []
    if not path or not os.path.isfile(path):
        return findings
    for lineno, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        requirement = line.split(";", 1)[0].strip()
        package_match = re.match(r"([A-Za-z0-9_.-]+)", requirement.lstrip("-e ").strip())
        package = package_match.group(1).lower().replace("_", "-") if package_match else None
        if line.startswith(("-e ", "--editable")):
            findings.append(_finding("PYRE-AUDIT-EDITABLE", "warning", "%s:%d %s" % (path, lineno, line), "Use an immutable pinned distribution for canister builds."))
        elif re.search(r"(?:git\+|https?://)", line):
            findings.append(_finding("PYRE-AUDIT-DIRECT-URL", "warning", "%s:%d %s" % (path, lineno, line), "Pin the URL to an immutable commit and require a hash."))
        elif "==" not in line and not line.startswith(("-r", "--requirement")):
            findings.append(_finding("PYRE-AUDIT-UNPINNED", "warning", "%s:%d %s" % (path, lineno, line), "Pin the exact tested version; unknown is not compatible."))
        if package and not line.startswith(("-r", "--requirement")):
            status, evidence = COMPATIBILITY.get(package, ("unknown", "no PYRE/Kybra compatibility test record"))
            if status == "incompatible":
                findings.append(_finding(
                    "PYRE-AUDIT-INCOMPATIBLE-PACKAGE", "error", evidence,
                    "Remove the package from canister dependencies or use a reviewed pure-Python/Wasm-compatible alternative.", package=package,
                ))
            elif status == "unknown":
                findings.append(_finding(
                    "PYRE-AUDIT-UNKNOWN-PACKAGE", "warning", evidence,
                    "Test this exact version under pinned Kybra/RustPython before declaring compatibility.", package=package,
                ))
            findings.extend(_audit_installed_distribution(package))
    return findings


def _audit_installed_distribution(package):
    findings = []
    try: distribution = importlib.metadata.distribution(package)
    except importlib.metadata.PackageNotFoundError:
        return findings
    files = distribution.files or []
    for item in sorted(str(value) for value in files):
        if item.lower().endswith(NATIVE_SUFFIXES):
            findings.append(_finding(
                "PYRE-AUDIT-NATIVE-EXTENSION", "error", "%s: %s" % (package, item),
                "Use a pure-Python distribution or remove it from the canister environment.", package=package,
            ))
    wheel = distribution.read_text("WHEEL") or ""
    if re.search(r"^Root-Is-Purelib:\s*false", wheel, re.I | re.M):
        findings.append(_finding(
            "PYRE-AUDIT-NON-PURE-WHEEL", "error", "%s WHEEL declares Root-Is-Purelib: false" % package,
            "Use a pure-Python wheel tested with RustPython.", package=package,
        ))
    return findings


def run(requirements=None, canister=None, strict=False):
    findings = audit_requirements(requirements)
    if canister:
        findings.extend(audit_canister(canister))
    findings.sort(key=lambda item: (item["code"], item["evidence"]))
    has_error = any(item["severity"] == "error" for item in findings)
    has_warning = any(item["severity"] == "warning" for item in findings)
    status = "fail" if has_error or (strict and has_warning) else "pass"
    environment = {"python": platform.python_version(), "pyre": __version__, "kybra": "0.7.1",
                   "compatibility_schema": COMPATIBILITY_SCHEMA}
    if canister:
        environment["canister_source_bytes"] = sum(
            os.path.getsize(path) for path in _python_files(canister) if os.path.isfile(path)
        )
    return {
        "schema": SCHEMA,
        "status": status,
        "environment": environment,
        "findings": findings,
    }, (2 if has_error else 1 if strict and has_warning else 0)
