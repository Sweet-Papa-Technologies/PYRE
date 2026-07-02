import sys

import pytest

from pyre.compat._stubs import _STUBBED, install_stubs


@pytest.fixture
def stubbed_modules():
    saved = {name: sys.modules.get(name) for name in _STUBBED}
    for name in _STUBBED:
        sys.modules.pop(name, None)
    install_stubs()
    yield
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def test_socket_stub_raises_with_guidance(stubbed_modules):
    import socket

    with pytest.raises(NotImplementedError, match="pyre.compat.urllib_request"):
        socket.socket()


def test_threading_stub_raises(stubbed_modules):
    import threading

    with pytest.raises(NotImplementedError, match="single-threaded"):
        threading.Thread(target=lambda: None)
