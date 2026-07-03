"""Fake-entropy defusal: in-canister, constant-returning entropy APIs must
raise with guidance instead of silently handing out predictable bytes.

install_stubs() only runs in_canister; these tests invoke the defusal
directly and restore the real functions afterwards.
"""

import os
import random
import secrets
import uuid

import pytest

from pyre.compat import _stubs


@pytest.fixture
def defused():
    saved = {
        "os.urandom": os.urandom,
        "uuid.uuid4": uuid.uuid4,
        "random.SystemRandom": random.SystemRandom,
        "secrets.SystemRandom": secrets.SystemRandom,
    }
    saved_secrets = {
        fn: getattr(secrets, fn)
        for fn in ("token_bytes", "token_hex", "token_urlsafe",
                   "randbits", "randbelow", "choice")
        if hasattr(secrets, fn)
    }
    _stubs._defuse_fake_entropy()
    yield
    os.urandom = saved["os.urandom"]
    uuid.uuid4 = saved["uuid.uuid4"]
    random.SystemRandom = saved["random.SystemRandom"]
    secrets.SystemRandom = saved["secrets.SystemRandom"]
    for fn, val in saved_secrets.items():
        setattr(secrets, fn, val)


def test_os_urandom_raises_with_guidance(defused):
    with pytest.raises(_stubs.FakeEntropyError) as exc:
        os.urandom(16)
    assert "pyre.random" in str(exc.value)
    assert "CONSTANT" in str(exc.value)


def test_uuid4_raises_but_hash_uuids_still_work(defused):
    with pytest.raises(_stubs.FakeEntropyError):
        uuid.uuid4()
    # uuid5 is hash-based and legitimately deterministic — must survive
    assert str(uuid.uuid5(uuid.NAMESPACE_DNS, "pyre.example")) == str(
        uuid.uuid5(uuid.NAMESPACE_DNS, "pyre.example"))


def test_secrets_functions_raise(defused):
    for call in (lambda: secrets.token_bytes(16),
                 lambda: secrets.token_hex(8),
                 lambda: secrets.token_urlsafe(8),
                 lambda: secrets.randbits(32),
                 lambda: secrets.choice([1, 2, 3])):
        with pytest.raises(_stubs.FakeEntropyError):
            call()


def test_compare_digest_untouched(defused):
    assert secrets.compare_digest(b"abc", b"abc") is True


def test_system_random_raises_but_plain_random_survives(defused):
    with pytest.raises(_stubs.FakeEntropyError):
        random.SystemRandom()
    random.random()  # legacy non-crypto uses keep working (dev-warned)


def test_failed_patch_never_raises():
    # a module without the attribute (or an unpatchable one) is skipped
    _stubs._patch("math", "urandom_does_not_exist_here")


def test_restore_worked():
    assert len(os.urandom(8)) == 8
    assert uuid.uuid4() != uuid.uuid4()
    assert secrets.token_hex(4) != secrets.token_hex(4)
