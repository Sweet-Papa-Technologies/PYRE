"""Runtime environment detection and per-dispatch context.

PYRE runs in two environments:
  - "canister": inside a Kybra canister (RustPython compiled to WASM on ICP)
  - "dev": on the host CPython (unit tests, `pyre dev` local runner)

Keep this module dependency-free; everything else in pyre imports it.
"""

import sys


def in_canister() -> bool:
    # Kybra executes canister code under RustPython; host tooling is CPython.
    return sys.implementation.name == "rustpython"


class _Context:
    """Per-dispatch flags set by the gateway/dev-server around handler calls."""

    def __init__(self):
        # True while a handler is executing in query context (no state
        # writes, no outcalls). The dev server also sets this for routes
        # that are not marked update, so ICP restrictions surface locally.
        self.in_query = False


ctx = _Context()
