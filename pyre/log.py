"""pyre.log — structured canister logging you can actually retrieve.

    from pyre import log

    @app.post("/items", update=True)
    def create(req):
        log.info("item created", id=item_id, caller=req.caller)

On a replica, entries go to the canister log via Kybra's ic.print
(ic0.debug_print), which the IC retains in a rolling canister-log buffer.
Retrieve them without redeploying:

    dfx canister logs <name>                 # local replica
    dfx canister logs <name> --network ic    # mainnet

In `pyre dev` (host CPython) entries print to stderr, so the dev loop
sees the same lines.

Notes:
  - The canister-log buffer is bounded (~4 KB per message, rolling
    window) — logs are for diagnostics, not an audit trail. Durable
    records belong in pyre.data.
  - Log lines are visible to anyone allowed to fetch canister logs
    (controller-only by default; `dfx canister update-settings
    --log-visibility public` opts into public logs). Never log secrets —
    the same rule as canister state.
  - In replicated execution every replica emits the line; the subnet
    keeps one copy. Nothing to deduplicate yourself.
"""

import json as _json

# Levels gate emission: set_level("warning") silences info/debug.
_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}
_config = {"level": 10}


def set_level(level):
    """Minimum level that gets emitted ("debug"|"info"|"warning"|"error")."""
    _config["level"] = _LEVELS[str(level).lower()]


def debug(message, **fields):
    _emit("debug", message, fields)


def info(message, **fields):
    _emit("info", message, fields)


def warning(message, **fields):
    _emit("warning", message, fields)


def error(message, **fields):
    _emit("error", message, fields)


def exception(message, exc, **fields):
    """Log an error with the exception's type and text attached."""
    fields["exc_type"] = type(exc).__name__
    fields["exc"] = str(exc)
    _emit("error", message, fields)


def _emit(level, message, fields):
    if _LEVELS[level] < _config["level"]:
        return
    line = "[%s] %s" % (level.upper(), message)
    if fields:
        try:
            line += " " + _json.dumps(fields, sort_keys=True, default=str)
        except Exception:
            line += " " + repr(fields)
    _print(line)


def _print(line):
    try:
        from kybra import ic  # lazy: canister runtime only
        ic.print(line)
    except ImportError:
        import sys
        print(line, file=sys.stderr)
