"""The `pyre` command: `pyre new <name>` and `pyre dev [app.py]`."""

import argparse
import os
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
            warn_reserved(os.path.dirname(os.path.abspath(candidate)) or ".")
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
