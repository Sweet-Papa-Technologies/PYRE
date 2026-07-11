"""Typed, guarded cross-canister calls."""

import re
import json
import base64
import binascii

from pyre import _platform as platform, log
from pyre._runtime import ctx
from pyre.candid import CandidDecodeError, CandidEncodeError

DEFAULT_MAX_PAYLOAD_BYTES = 1_900_000
MAX_REJECTION_CHARS = 256
_PRINCIPAL = re.compile(r"^[a-z0-9]{1,5}(?:-[a-z0-9]{1,5})*$")


def _valid_principal(value):
    if not isinstance(value, str) or not _PRINCIPAL.match(value): return False
    compact = value.replace("-", "")
    try:
        decoded = base64.b32decode(compact.upper() + "=" * (-len(compact) % 8))
    except Exception:
        return False
    if len(decoded) < 4 or len(decoded) > 33: return False
    canonical = base64.b32encode(decoded).decode("ascii").lower().rstrip("=")
    if canonical != compact: return False
    checksum, principal = decoded[:4], decoded[4:]
    return checksum == (binascii.crc32(principal) & 0xFFFFFFFF).to_bytes(4, "big")


class XNetError(RuntimeError): code = "PYRE-XNET-ERROR"
class UnknownMethod(XNetError): code = "PYRE-XNET-UNKNOWN-METHOD"
class QueryContextCallError(XNetError): code = "PYRE-XNET-QUERY-CALL"
class PayloadTooLarge(XNetError):
    code = "PYRE-XNET-PAYLOAD-LARGE"
    def __init__(self, actual, allowed):
        self.actual, self.allowed = actual, allowed
        super().__init__("payload is %d bytes; maximum is %d" % (actual, allowed))
class CanisterRejected(XNetError):
    code = "PYRE-XNET-REJECTED"
    def __init__(self, reject_code, message):
        self.reject_code = reject_code
        self.message = str(message).replace("\r", " ").replace("\n", " ")[:MAX_REJECTION_CHARS]
        super().__init__("canister rejected call (%s): %s" % (reject_code, self.message))
class CallTransportError(XNetError): code = "PYRE-XNET-TRANSPORT"


class PlatformTransport:
    def encode(self, method, args):
        return platform.candid_encode(
            "(" + ", ".join(_candid_text(spec, value) for spec, value in zip(method.args, args)) + ")"
        )
    def decode(self, method, payload):
        decoded = platform.candid_decode(payload)
        if isinstance(decoded, str):
            values = _decode_candid_text(decoded, method.returns)
        else:
            values = decoded if isinstance(decoded, (list, tuple)) else (decoded,)
        if len(values) != len(method.returns):
            raise CandidDecodeError("%s expected %d return value(s), got %d" % (
                method.name, len(method.returns), len(values)))
        for index, (spec, value) in enumerate(zip(method.returns, values)):
            try: spec.validate(value, "%s return %d" % (method.name, index + 1))
            except CandidEncodeError as exc: raise CandidDecodeError(str(exc))
        if not values: return None
        return values[0] if len(values) == 1 else tuple(values)
    def call(self, canister_id, method, payload, cycles):
        return _RawCall(canister_id, method, payload, cycles)
    def notify(self, canister_id, method, payload, cycles):
        return platform.notify_raw(canister_id, method, payload, cycles=cycles)


class _RawCall:
    def __init__(self, canister_id, method, payload, cycles):
        self.canister_id, self.method, self.payload, self.cycles = canister_id, method, payload, cycles
    def __await__(self):
        result = yield self
        return result
    __iter__ = __await__
    def _to_kybra_call(self):
        return platform.call_raw(self.canister_id, self.method, self.payload, cycles=self.cycles)
    def _process_call_result(self, result):
        if isinstance(result, dict):
            error, value = result.get("Err"), result.get("Ok")
        else:
            error, value = getattr(result, "Err", None), getattr(result, "Ok", None)
        if error is not None:
            code = getattr(error, "code", None) or (error.get("code") if isinstance(error, dict) else "unknown")
            raise CanisterRejected(code, error)
        return bytes(value)


def _candid_text(spec, value):
    """Deterministic textual Candid accepted by Kybra's reviewed codec."""
    kind = spec.kind
    if kind == "null": return "null"
    if kind == "bool": return "true" if value else "false"
    if kind == "text":
        import json
        return json.dumps(value, ensure_ascii=True)
    if kind == "principal":
        import json
        return "principal " + json.dumps(value)
    if kind == "blob": return "blob \"" + "".join("\\%02x" % byte for byte in value) + "\""
    if kind in ("nat", "int", "nat8", "nat16", "nat32", "nat64", "int8", "int16", "int32", "int64", "float32", "float64"):
        return str(value)
    if kind == "opt": return "null" if value is None else "opt " + _candid_text(spec.inner, value)
    if kind == "vec":
        values = value if not isinstance(value, (bytes, bytearray)) else list(value)
        return "vec { " + "; ".join(_candid_text(spec.inner, item) for item in values) + " }"
    if kind == "record":
        return "record { " + "; ".join("%s = %s" % (name, _candid_text(field, value.get(name))) for name, field in spec.fields) + " }"
    if kind == "variant":
        name = next(iter(value)); field = dict(spec.fields)[name]
        return "variant { %s = %s }" % (name, _candid_text(field, value[name]))
    raise CandidEncodeError("unsupported Candid type %s" % kind)


_VALUE_TOKEN = re.compile(
    r'\s+|"(?:\\.|[^"\\])*"|[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|'
    r'[A-Za-z_][A-Za-z0-9_]*|[{}(),;=:]', re.S
)


class _ValueParser:
    def __init__(self, text):
        self.text, self.tokens, offset = text, [], 0
        while offset < len(text):
            match = _VALUE_TOKEN.match(text, offset)
            if not match: raise CandidDecodeError("unexpected Candid value token at offset %d" % offset)
            token = match.group(0); offset = match.end()
            if not token.isspace(): self.tokens.append(token)
        self.tokens.append("<eof>"); self.index = 0
    def peek(self): return self.tokens[self.index]
    def take(self): value = self.peek(); self.index += 1; return value
    def expect(self, value):
        if self.peek() != value: raise CandidDecodeError("got %r; expected %s" % (self.peek(), value))
        return self.take()
    def label(self):
        token = self.take()
        return json.loads(token) if token.startswith('"') else token
    def annotation(self):
        if self.peek() != ":": return
        self.take(); depth = 0
        while self.peek() != "<eof>":
            token = self.peek()
            if depth == 0 and token in (",", ";", ")", "}"): return
            token = self.take()
            if token in ("(", "{"): depth += 1
            elif token in (")", "}"): depth -= 1
    def value(self, spec):
        kind = spec.kind
        if kind == "opt":
            if self.peek() == "null": self.take(); return None
            self.expect("opt"); return self.value(spec.inner)
        if kind == "vec":
            if self.peek() == "blob":
                self.take(); token = self.take()
                if not token.startswith('"'): raise CandidDecodeError("blob requires a quoted value")
                raw, index = bytearray(), 1
                while index < len(token) - 1:
                    if token[index] == "\\" and index + 2 < len(token) - 1:
                        try: raw.append(int(token[index + 1:index + 3], 16)); index += 3; continue
                        except ValueError: pass
                    raw.extend(token[index].encode("utf-8")); index += 1
                value = bytes(raw)
                return value if spec.inner.kind == "nat8" else list(value)
            self.expect("vec"); self.expect("{"); result = []
            while self.peek() != "}":
                result.append(self.value(spec.inner)); self.annotation()
                if self.peek() in (";", ","): self.take()
                elif self.peek() != "}": self.expect(";")
            self.take(); return result
        if kind in ("record", "variant"):
            self.expect(kind); self.expect("{"); available, result = dict(spec.fields), {}
            while self.peek() != "}":
                name = self.label(); self.expect("=")
                if name not in available: raise CandidDecodeError("unknown %s field %s" % (kind, name))
                result[name] = self.value(available[name]); self.annotation()
                if self.peek() in (";", ","): self.take()
                elif self.peek() != "}": self.expect(";")
            self.take(); return result
        if kind == "null": self.expect("null"); return None
        if kind == "bool":
            token = self.take()
            if token not in ("true", "false"): raise CandidDecodeError("expected bool")
            return token == "true"
        if kind == "principal":
            self.expect("principal"); token = self.take()
            if not token.startswith('"'): raise CandidDecodeError("principal must be quoted")
            return json.loads(token)
        if kind == "blob":
            return self.value(type(spec)("vec", inner=type(spec)("nat8")))
        if kind == "text":
            token = self.take()
            if not token.startswith('"'): raise CandidDecodeError("expected quoted text")
            return json.loads(token)
        if kind in ("float32", "float64"):
            try: return float(self.take())
            except ValueError: raise CandidDecodeError("expected floating-point number")
        if kind in ("nat", "int", "nat8", "nat16", "nat32", "nat64", "int8", "int16", "int32", "int64"):
            try: return int(self.take())
            except ValueError: raise CandidDecodeError("expected integer")
        raise CandidDecodeError("unsupported decoded Candid type %s" % kind)


def _decode_candid_text(text, specs):
    parser = _ValueParser(text); parser.expect("("); values = []
    while parser.peek() != ")":
        if len(values) >= len(specs): raise CandidDecodeError("too many Candid return values")
        values.append(parser.value(specs[len(values)])); parser.annotation()
        if parser.peek() == ",": parser.take()
        elif parser.peek() != ")": parser.expect(",")
    parser.take()
    if parser.peek() != "<eof>": raise CandidDecodeError("trailing Candid response data")
    return tuple(values)


class CanisterClient:
    def __init__(self, canister_id, service, *, default_cycles=0,
                 max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES, transport=None):
        if not _valid_principal(canister_id):
            raise ValueError("invalid canister principal %r" % canister_id)
        if not isinstance(max_payload_bytes, int) or max_payload_bytes <= 0 or max_payload_bytes > DEFAULT_MAX_PAYLOAD_BYTES:
            raise ValueError("max_payload_bytes must be between 1 and %d" % DEFAULT_MAX_PAYLOAD_BYTES)
        if not isinstance(default_cycles, int) or default_cycles < 0:
            raise ValueError("default_cycles must be a non-negative integer")
        self.canister_id, self.service = canister_id, service
        self.default_cycles, self.max_payload_bytes = default_cycles, max_payload_bytes
        self.transport = transport or PlatformTransport()

    def method(self, name):
        try: return self.service.method(name)
        except KeyError: raise UnknownMethod("service %s has no method %r" % (self.service.name, name))

    def _encode(self, name, args):
        method = self.method(name); method.validate_args(args)
        try: payload = bytes(self.transport.encode(method, args))
        except CandidEncodeError: raise
        except Exception as exc: raise CandidEncodeError("%s encode failed: %s" % (name, str(exc)[:256]))
        if len(payload) > self.max_payload_bytes: raise PayloadTooLarge(len(payload), self.max_payload_bytes)
        return method, payload

    async def call(self, method, *args, cycles=None, timeout=None):
        if ctx.in_query: raise QueryContextCallError("cross-canister calls require update context")
        spec, payload = self._encode(method, args)
        payment = self.default_cycles if cycles is None else cycles
        if not isinstance(payment, int) or payment < 0: raise ValueError("cycles must be a non-negative integer")
        log.info("xnet.call_started", canister=self.canister_id, method=method, bytes=len(payload), cycles=payment)
        try:
            reply = await self.transport.call(self.canister_id, method, payload, payment)
        except CanisterRejected: raise
        except Exception as exc: raise CallTransportError("call transport failed: %s" % str(exc)[:256])
        if len(reply) > self.max_payload_bytes: raise PayloadTooLarge(len(reply), self.max_payload_bytes)
        try: result = self.transport.decode(spec, reply)
        except Exception as exc: raise CandidDecodeError("%s response did not match expected type: %s" % (method, str(exc)[:256]))
        log.info("xnet.call_succeeded", canister=self.canister_id, method=method, bytes=len(reply))
        return result

    def notify(self, method, *args, cycles=None):
        if ctx.in_query: raise QueryContextCallError("cross-canister notifications require update context")
        _spec, payload = self._encode(method, args)
        payment = self.default_cycles if cycles is None else cycles
        if not isinstance(payment, int) or payment < 0: raise ValueError("cycles must be a non-negative integer")
        try: return self.transport.notify(self.canister_id, method, payload, payment)
        except Exception as exc: raise CallTransportError("notify transport failed: %s" % str(exc)[:256])
