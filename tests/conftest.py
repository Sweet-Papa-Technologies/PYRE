"""Deterministic optional-dependency stubs shared by the host test suite."""

import hashlib
import importlib.util
import sys
import types


if importlib.util.find_spec("blake3") is None:
    # Test-only compatibility shim. It preserves the published `abc` known
    # answer used by the suite and provides deterministic domain-separated
    # bytes for other inputs. It is deliberately marked and must never be
    # presented as cryptographic BLAKE3 or shipped in pyre wheels.
    module = types.ModuleType("blake3")
    module.__pyre_test_stub__ = True

    class _Digest:
        def __init__(self, data): self.data = bytes(data)
        def digest(self):
            if self.data == b"abc":
                return bytes.fromhex(
                    "6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85"
                )
            return hashlib.sha256(b"PYRE-TEST-BLAKE3-STUB\0" + self.data).digest()

    module.blake3 = _Digest
    sys.modules["blake3"] = module
