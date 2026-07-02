#!/usr/bin/env python3
"""External verifier for pyre.sign — the Phase-3 acceptance gate.

The canister signs with a threshold key held by the subnet; this script
verifies the signature OUTSIDE the IC, against the canister's public key,
proving the signature is real secp256k1 ECDSA anyone can check.

Usage:
  # verify a signed JWT (ES256K) against a SEC1 public key (hex):
  python scripts/verify_signature.py jwt <token> <pubkey-hex>

  # verify a raw detached signature over a message:
  python scripts/verify_signature.py raw <message> <signature-hex> <pubkey-hex>

  # negative self-check (tampered payload must FAIL):
  python scripts/verify_signature.py jwt <token> <pubkey-hex> --tamper

Runs on the host (dev venv): pip install ecdsa. Exits 0 when the observed
outcome matches the expectation, 1 otherwise.
"""

import base64
import hashlib
import json
import sys

try:
    import ecdsa
except ImportError:
    sys.exit("pip install ecdsa (into .venv-dev) first")


def b64url_decode(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def verify(pub_hex, signature, message_bytes):
    vk = ecdsa.VerifyingKey.from_string(bytes.fromhex(pub_hex), curve=ecdsa.SECP256k1)
    digest = hashlib.sha256(message_bytes).digest()
    return vk.verify_digest(signature, digest)


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    mode = argv[0]
    tamper = "--tamper" in argv
    argv = [a for a in argv if a != "--tamper"]

    if mode == "jwt":
        token, pub_hex = argv[1], argv[2]
        header_b64, payload_b64, sig_b64 = token.split(".")
        header = json.loads(b64url_decode(header_b64))
        if header.get("alg") != "ES256K":
            sys.exit("FAIL: expected alg ES256K, got %r" % header.get("alg"))
        signing_input = (header_b64 + "." + payload_b64).encode("ascii")
        if tamper:
            payload = json.loads(b64url_decode(payload_b64))
            payload["__tampered"] = True
            tampered_b64 = base64.urlsafe_b64encode(
                json.dumps(payload).encode()).rstrip(b"=").decode()
            signing_input = (header_b64 + "." + tampered_b64).encode("ascii")
        signature = b64url_decode(sig_b64)
        message = signing_input
        claims = json.loads(b64url_decode(payload_b64))
    elif mode == "raw":
        message = argv[1].encode("utf-8")
        signature = bytes.fromhex(argv[2])
        pub_hex = argv[3]
        if tamper:
            message += b"!"
        claims = None
    else:
        sys.exit(__doc__)

    try:
        verify(pub_hex, signature, message)
        ok = True
    except ecdsa.BadSignatureError:
        ok = False

    if tamper:
        if ok:
            print("UNEXPECTED PASS — verifier accepted a tampered payload")
            return 1
        print("EXPECTED FAIL (tampered): signature correctly rejected")
        return 0
    if ok:
        print("PASS: signature verifies externally against the canister public key"
              " (secp256k1/sha256)")
        if claims is not None:
            print("claims:", json.dumps(claims, indent=2))
        return 0
    print("FAIL: signature does not verify")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
