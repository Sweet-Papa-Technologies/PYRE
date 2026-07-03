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
    _defuse_fake_entropy()


# -- fake-entropy defusal ------------------------------------------------------
# The v1.1 stdlib audit found that in-canister os.urandom / secrets.* /
# uuid.uuid4 return CONSTANTS (the same bytes/UUID on every call, forever)
# because the RustPython/WASI build has no entropy source. These APIs carry
# a cryptographic-strength contract we cannot honor synchronously (the only
# real entropy, raw_rand, is an async system call), so the honest move is
# the same as for socket/threading: fail loudly with guidance instead of
# silently returning predictable "randomness" (session tokens, salts,
# ids...). Consensus-safe alternatives live in pyre.random.

_ENTROPY_GUIDANCE = (
    " returns a CONSTANT inside a canister (no entropy source in the "
    "interpreter) — this is never random. For ids use pyre.random.uuid4(); "
    "for cryptographic bytes use `await pyre.random.raw_bytes(n)` "
    "(update context); see docs/random-uuid-time.md"
)


class FakeEntropyError(NotImplementedError):
    """A stdlib entropy API that silently returns constants in-canister."""


def _defuse(qualname):
    def raiser(*args, **kwargs):
        raise FakeEntropyError(qualname + "()" + _ENTROPY_GUIDANCE)

    raiser.__name__ = qualname.rsplit(".", 1)[-1]
    return raiser


def _patch(module_name, attr):
    """Best-effort defusal: never let a failed patch break canister init."""
    try:
        module = __import__(module_name)
        setattr(module, attr, _defuse("%s.%s" % (module_name, attr)))
    except Exception:
        pass  # leave the footgun to the dev-time warnings rather than brick @init


def _defuse_fake_entropy():
    _patch("os", "urandom")
    # uuid1 needs urandom too and trips the os.urandom defusal on its
    # own; uuid3/5 are hash-based and legitimately deterministic.
    _patch("uuid", "uuid4")
    for fn in ("token_bytes", "token_hex", "token_urlsafe",
               "randbits", "randbelow", "choice"):
        _patch("secrets", fn)  # NOT compare_digest — that one is fine
    # SystemRandom claims OS entropy and is Rust-backed (bypasses the
    # os.urandom defusal at the Python level) — fail at instantiation.
    _patch("secrets", "SystemRandom")
    # plain random.random()/randint() restart an IDENTICAL stream every
    # message — ugly but not a crypto contract; left to dev warnings.
    _patch("random", "SystemRandom")
