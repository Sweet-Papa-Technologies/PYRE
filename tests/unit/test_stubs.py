import sys

import pytest

from pyre.compat._stubs import _STUBBED, install_stubs


@pytest.fixture
def stubbed_modules():
    import os
    import random
    import secrets
    import uuid

    saved = {name: sys.modules.get(name) for name in _STUBBED}
    # install_stubs() also defuses the fake-entropy APIs — save them so
    # the rest of the (host-side) suite keeps real entropy afterwards
    saved_entropy = [
        (os, "urandom", os.urandom),
        (uuid, "uuid4", uuid.uuid4),
        (random, "SystemRandom", random.SystemRandom),
        (secrets, "SystemRandom", secrets.SystemRandom),
    ] + [
        (secrets, fn, getattr(secrets, fn))
        for fn in ("token_bytes", "token_hex", "token_urlsafe",
                   "randbits", "randbelow", "choice")
        if hasattr(secrets, fn)
    ]
    for name in _STUBBED:
        sys.modules.pop(name, None)
    install_stubs()
    yield
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
    for module, attr, value in saved_entropy:
        setattr(module, attr, value)


def test_socket_stub_raises_with_guidance(stubbed_modules):
    import socket

    with pytest.raises(NotImplementedError, match="pyre.compat.urllib_request"):
        socket.socket()


def test_threading_stub_raises(stubbed_modules):
    import threading

    with pytest.raises(NotImplementedError, match="single-threaded"):
        threading.Thread(target=lambda: None)
