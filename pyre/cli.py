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
    "cors", "validation", "certification", "transform", "outcall", "errors", "static",
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
    # pip byte-compiles installed templates; don't ship the caches
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__"))
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


def _http_json(method, url, token=None, payload=None, timeout=60):
    """One JSON-over-HTTP exchange. Returns (status, parsed_body_or_None).

    Raises on transport errors (connection refused, DNS, timeout); HTTP
    error statuses are returned, not raised."""
    import json as _json
    import urllib.error
    import urllib.request

    headers = {"accept": "application/json"}
    if token:
        headers["authorization"] = "Bearer " + token
    data = None
    if payload is not None:
        data = _json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body, status = resp.read(), resp.status
    except urllib.error.HTTPError as e:
        body, status = e.read(), e.code
    try:
        parsed = _json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        parsed = None
    return status, parsed


def _push_call(method, url, token, payload, tries=3):
    """_http_json with retries (transport errors and 5xx; backoff 1s/2s)."""
    import time as _time

    delay = 1.0
    last_error = None
    for attempt in range(tries):
        try:
            status, parsed = _http_json(method, url, token, payload)
        except Exception as e:  # noqa: BLE001 — URLError, socket, timeout
            last_error = e
        else:
            if status < 500 or attempt == tries - 1:
                return status, parsed
            last_error = "HTTP %d" % status
        if attempt < tries - 1:
            _time.sleep(delay)
            delay *= 2
    raise RuntimeError("request to %s failed after %d tries: %s" % (url, tries, last_error))


def cmd_assets_push(args):
    """Upload a built dist/ directory to a canister's static asset store.

    Speaks the pyre.static upload protocol (manifest → chunks → finalize)
    over plain HTTP, so it works identically against `pyre dev`, a local
    replica, and mainnet — anywhere the app's admin routes are reachable."""
    import base64
    import gzip
    import hashlib

    from pyre.static import (
        CHUNK_RAW_SIZE,
        MAX_ASSET_BYTES,
        content_type_for,
        is_compressible,
    )

    dist = os.path.abspath(args.dist)
    if not os.path.isdir(dist):
        print("error: %s is not a directory" % dist, file=sys.stderr)
        return 1
    admin = args.url.rstrip("/") + args.admin_prefix

    # 1. collect local files (gzipping compressible ones where it helps)
    local = []
    oversize = 0
    for root, _dirs, names in os.walk(dist):
        for name in sorted(names):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, dist).replace(os.sep, "/")
            with open(full, "rb") as f:
                data = f.read()
            if len(data) > MAX_ASSET_BYTES:
                print(
                    "  WARNING: skipping %s — %d bytes exceeds the %d-byte cap "
                    "(canister responses must stay under ~2MB)"
                    % (rel, len(data), MAX_ASSET_BYTES),
                    file=sys.stderr,
                )
                oversize += 1
                continue
            gz = None
            if not args.no_gzip and is_compressible(rel):
                candidate = gzip.compress(data, 9, mtime=0)
                if len(candidate) < len(data):
                    gz = candidate
            local.append((rel, data, gz))
    if not local:
        print("error: no uploadable files under %s" % dist, file=sys.stderr)
        return 1

    # 2. skip files the canister already has (same raw sha256, same gzip-ness)
    status, listing = _push_call("GET", admin + "/list", args.token, None)
    if status == 401:
        print("error: token rejected (401) by %s" % admin, file=sys.stderr)
        return 1
    remote = (listing or {}).get("assets", {}) if status == 200 else {}
    to_send, unchanged = [], 0
    for rel, data, gz in local:
        have = remote.get(rel)
        if (
            have
            and have.get("sha256") == hashlib.sha256(data).hexdigest()
            and bool(have.get("gzip")) == (gz is not None)
        ):
            unchanged += 1
            continue
        to_send.append((rel, data, gz))
    if not to_send:
        print("everything up to date (%d file(s) unchanged)" % unchanged)
        return 0

    # 3. manifest
    manifest = {}
    for rel, data, gz in to_send:
        entry = {
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_type": content_type_for(rel),
        }
        if gz is not None:
            entry["gzip_size"] = len(gz)
            entry["gzip_sha256"] = hashlib.sha256(gz).hexdigest()
        manifest[rel] = entry
    status, out = _push_call("POST", admin + "/manifest", args.token, {"assets": manifest})
    accepted = (out or {}).get("accepted") or {}
    rejected = (out or {}).get("rejected") or {}
    for rel in sorted(rejected):
        print("  WARNING: %s rejected: %s" % (rel, rejected[rel]), file=sys.stderr)
    if status != 200 or not accepted:
        print("error: manifest rejected (HTTP %d)" % status, file=sys.stderr)
        return 1

    # 4. chunks (raw + gzip variants)
    wire_bytes = 0
    for rel, data, gz in to_send:
        if rel not in accepted:
            continue
        for variant, blob in (("raw", data), ("gzip", gz)):
            if blob is None:
                continue
            slices = [
                blob[i : i + CHUNK_RAW_SIZE] for i in range(0, len(blob), CHUNK_RAW_SIZE)
            ] or [b""]
            for index, piece in enumerate(slices):
                payload = {
                    "path": rel,
                    "variant": variant,
                    "index": index,
                    "data": base64.b64encode(piece).decode("ascii"),
                }
                status, out = _push_call("POST", admin + "/chunk", args.token, payload)
                if status != 200:
                    print(
                        "error: chunk %s [%s %d] rejected (HTTP %d): %s"
                        % (rel, variant, index, status, out),
                        file=sys.stderr,
                    )
                    return 1
                wire_bytes += len(piece)
        print("  %s (%d bytes%s)" % (rel, len(data), ", +gzip" if gz is not None else ""))

    # 5. finalize (verifies sha256s server-side, then swaps atomically)
    paths = [rel for rel, _, _ in to_send if rel in accepted]
    status, out = _push_call("POST", admin + "/finalize", args.token, {"paths": paths})
    errors = (out or {}).get("errors") or {}
    if status != 200 or errors:
        for rel in sorted(errors):
            print("error: finalize %s: %s" % (rel, errors[rel]), file=sys.stderr)
        print("error: finalize failed (HTTP %d)" % status, file=sys.stderr)
        return 1
    gz_count = sum(1 for _, _, gz in to_send if gz is not None)
    print(
        "pushed %d file(s), %d bytes on the wire (%d gzipped); %d unchanged, %d rejected"
        % (len(paths), wire_bytes, gz_count, unchanged, len(rejected) + oversize)
    )
    return 0


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

    p_assets = sub.add_parser("assets", help="manage a canister's static asset store")
    assets_sub = p_assets.add_subparsers(dest="assets_command", required=True)
    p_push = assets_sub.add_parser(
        "push", help="upload a built frontend (dist/) via the pyre.static protocol"
    )
    p_push.add_argument("dist", help="path to the built frontend directory (e.g. dist/)")
    p_push.add_argument(
        "--url",
        required=True,
        help="app base URL: http://127.0.0.1:8000 (pyre dev), "
        "http://<id>.localhost:4943 (replica), https://<id>.icp0.io (mainnet)",
    )
    p_push.add_argument("--token", required=True, help="bearer token for the admin routes")
    p_push.add_argument(
        "--admin-prefix",
        default="/_pyre/static",
        help="where static.admin_routes() is mounted (default: /_pyre/static)",
    )
    p_push.add_argument("--no-gzip", action="store_true", help="skip gzip variants")
    p_push.set_defaults(func=cmd_assets_push)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
