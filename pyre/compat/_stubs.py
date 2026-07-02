"""Informative stubs for modules that cannot work on ICP (§5.6).

Silent partial support is worse than a clear failure: importing `socket`
inside the canister gets you a module whose every attribute raises
NotImplementedError pointing at the PYRE alternative.
"""

import sys

_STUBBED = {
    "socket": "raw sockets aren't available on ICP; use pyre.compat.urllib_request for outbound HTTPS",
    "threading": "threads aren't available on ICP; canisters are single-threaded actors",
    "multiprocessing": "processes aren't available on ICP; canisters are single-threaded actors",
    "subprocess": "subprocesses aren't available on ICP",
    "select": "raw I/O multiplexing isn't available on ICP; use pyre.compat.urllib_request",
    "ssl": "TLS is terminated by the platform; use pyre.compat.urllib_request for HTTPS",
}


class _StubModule:
    def __init__(self, name, reason):
        self.__name__ = name
        self._reason = reason

    def __getattr__(self, attr):
        raise NotImplementedError(
            "%s.%s is not available on the Internet Computer: %s"
            % (self.__name__, attr, self._reason)
        )


def install_stubs():
    for name, reason in _STUBBED.items():
        if name not in sys.modules:
            sys.modules[name] = _StubModule(name, reason)
