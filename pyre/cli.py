"""The `pyre` command: `pyre new <name>` and `pyre dev [app.py]`."""

import argparse
import os
import re
import shutil
import sys


# Module basenames a user file must not use: Kybra's bundler flattens every
# module to a top-level <basename>.py slot and later copies silently win
# (see DECISIONS.md "Kybra bundler limitations").
RESERVED_BASENAMES = {
    # pyre framework modules
    "application", "http_types", "routing", "gateway", "kv", "data", "auth",
    "cors", "validation", "certification", "transform", "outcall", "errors",
    "dev", "cli", "_runtime", "_stubs", "urllib_request",
    "prandom", "ptime", "puuid",
    # kybra-internal modules
    "http", "basic", "bitcoin", "tecdsa", "principal",
}


def check_reserved_basenames(directory):
    """Returns a list of offending user files (checked by pyre new/dev)."""
    offenders = []
    for root, _dirs, files in os.walk(directory):
        for name in files:
            stem, ext = os.path.splitext(name)
            if ext == ".py" and stem in RESERVED_BASENAMES:
                offenders.append(os.path.join(root, name))
    return offenders


def warn_reserved(directory):
    for path in check_reserved_basenames(directory):
        print(
            "pyre: WARNING — %s uses a reserved module basename; Kybra's bundler "
            "will silently clobber it on deploy. Rename the file. (Reserved: %s)"
            % (path, ", ".join(sorted(RESERVED_BASENAMES))),
            file=sys.stderr,
        )


# Nondeterminism footguns: update calls execute replicated across ~13 nodes,
# so host entropy / wall-clock sources compute a DIFFERENT value on every
# replica — breaking consensus or silently diverging. Scanned by `pyre dev`.
FOOTGUN_PATTERNS = (
    (
        re.compile(r"(?:^|\s)(?:import\s+random\b|from\s+random\s+import\b)"),
        "use pyre.random (from pyre import random as prandom) — naive random "
        "draws per-replica entropy and breaks consensus in update calls",
    ),
    (
        re.compile(r"(?:^|\s)(?:import\s+uuid\b|from\s+uuid\s+import\b)|\buuid\.uuid4\s*\("),
        "use pyre.random.uuid4() / await pyre.random.uuid4_strong() — "
        "uuid.uuid4 draws per-replica entropy and breaks consensus in update calls",
    ),
    (
        re.compile(r"\bdatetime\.(?:now|utcnow)\s*\(|\btime\.time(?:_ns)?\s*\("),
        "use pyre.time (from pyre import time as ptime) — wall-clock time "
        "differs on every replica; ptime wraps the consensus-safe ic.time()",
    ),
    (
        re.compile(
            r"(?:^|\s)(?:import\s+secrets\b|from\s+secrets\s+import\b)"
            r"|\bos\.urandom\s*\("
        ),
        "use await pyre.random.raw_bytes(n) — in-canister os.urandom/secrets "
        "are CONSTANT stubs under Kybra (the same bytes every call, forever); "
        "they are never a source of randomness, let alone a safe one",
    ),
)

# Lines that already use the pyre-blessed spellings never warn.
_PYRE_BLESSED = re.compile(r"(?:^|\s)(?:from\s+pyre\b|import\s+pyre\b)|\bpyre\.")

# Directories that hold framework/vendored code, not the user's app.
_SKIP_DIRS = {"pyre", "kybra", "site-packages", "node_modules", "__pycache__"}


def check_footguns(directory):
    """Scan user .py files for nondeterminism footguns.

    Returns a list of (path, lineno, message). Line-based on purpose:
    cheap, obvious, and good enough for a dev-time warning (comment lines
    and pyre-blessed imports are excluded; pyre's own modules are skipped).
    """
    findings = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [
            d for d in dirs
            if d not in _SKIP_DIRS and not d.startswith(".") and d != "venv"
        ]
        for name in sorted(files):
            stem, ext = os.path.splitext(name)
            if ext != ".py" or stem in RESERVED_BASENAMES:
                continue  # framework files are exempt (and already warned on)
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if _PYRE_BLESSED.search(stripped):
                    continue
                for pattern, message in FOOTGUN_PATTERNS:
                    if pattern.search(stripped):
                        findings.append((path, lineno, message))
                        break  # one warning per line is plenty
    return findings


def warn_footguns(directory):
    for path, lineno, message in check_footguns(directory):
        print(
            "pyre: WARNING — %s:%d: %s" % (path, lineno, message),
            file=sys.stderr,
        )


def _templates_dir(template):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", template)


def cmd_new(args):
    dest = os.path.abspath(args.name)
    if os.path.exists(dest):
        print("error: %s already exists" % dest, file=sys.stderr)
        return 1
    source = _templates_dir(args.template)
    if not os.path.isdir(source):
        available = sorted(os.listdir(os.path.dirname(source)))
        print(
            "error: unknown template %r (available: %s)" % (args.template, ", ".join(available)),
            file=sys.stderr,
        )
        return 1
    project = os.path.basename(dest)
    shutil.copytree(source, dest)
    # stamp the project name into dfx.json and README
    for rel in ("dfx.json", "README.md"):
        path = os.path.join(dest, rel)
        with open(path) as f:
            content = f.read()
        with open(path, "w") as f:
            f.write(content.replace("__PROJECT_NAME__", project))
    warn_reserved(os.path.join(dest, "src"))
    print("created %s (template: %s)" % (dest, args.template))
    print("next steps:")
    print("  cd %s" % args.name)
    print("  pyre dev src/app.py          # instant local iteration")
    print("  dfx start --background && dfx deploy   # local replica")
    return 0


def _load_app(path):
    import importlib.util

    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    spec = importlib.util.spec_from_file_location("__pyre_dev_app__", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = getattr(module, "app", None)
    if app is None:
        print("error: %s does not define a module-level `app`" % path, file=sys.stderr)
        sys.exit(1)
    return app


def cmd_dev(args):
    from pyre.dev import serve

    candidates = [args.app] if args.app else ["src/app.py", "app.py"]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            app_dir = os.path.dirname(os.path.abspath(candidate)) or "."
            warn_reserved(app_dir)
            warn_footguns(app_dir)
            app = _load_app(candidate)
            serve(app, host=args.host, port=args.port)
            return 0
    print(
        "error: no app file found (tried: %s); pass one explicitly: pyre dev path/to/app.py"
        % ", ".join(c for c in candidates if c),
        file=sys.stderr,
    )
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pyre", description="PYRE — Python on the Internet Computer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="create a new PYRE project")
    p_new.add_argument("name")
    p_new.add_argument(
        "--template",
        default="bare-api",
        help="bare-api (default), crud-kv, or outbound-proxy",
    )
    p_new.set_defaults(func=cmd_new)

    p_dev = sub.add_parser("dev", help="run the app locally (no replica needed)")
    p_dev.add_argument("app", nargs="?", help="path to the module defining `app` (default: src/app.py)")
    p_dev.add_argument("--host", default="127.0.0.1")
    p_dev.add_argument("--port", type=int, default=8000)
    p_dev.set_defaults(func=cmd_dev)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
