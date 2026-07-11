"""Lightweight runtime Candid specifications used by generated clients."""

from dataclasses import dataclass


class CandidError(ValueError):
    code = "PYRE-CANDID-ERROR"


class CandidEncodeError(CandidError):
    code = "PYRE-CANDID-ENCODE"


class CandidDecodeError(CandidError):
    code = "PYRE-CANDID-DECODE"


_INT_BOUNDS = {
    "nat8": (0, 2**8 - 1), "nat16": (0, 2**16 - 1),
    "nat32": (0, 2**32 - 1), "nat64": (0, 2**64 - 1),
    "int8": (-(2**7), 2**7 - 1), "int16": (-(2**15), 2**15 - 1),
    "int32": (-(2**31), 2**31 - 1), "int64": (-(2**63), 2**63 - 1),
}


@dataclass(frozen=True)
class TypeSpec:
    kind: str
    inner: object = None
    fields: tuple = ()

    @classmethod
    def opt(cls, inner):
        return cls("opt", inner=inner)

    @classmethod
    def vec(cls, inner):
        return cls("vec", inner=inner)

    @classmethod
    def record(cls, fields):
        return cls("record", fields=tuple(sorted(fields.items())))

    @classmethod
    def variant(cls, fields):
        return cls("variant", fields=tuple(sorted(fields.items())))

    def validate(self, value, path="value"):
        kind = self.kind
        if kind == "null":
            if value is not None: raise CandidEncodeError("%s must be null" % path)
        elif kind == "bool":
            if type(value) is not bool: raise CandidEncodeError("%s must be bool" % path)
        elif kind in ("text", "principal"):
            if not isinstance(value, str): raise CandidEncodeError("%s must be %s" % (path, kind))
        elif kind == "blob":
            if not isinstance(value, (bytes, bytearray)): raise CandidEncodeError("%s must be bytes" % path)
        elif kind in ("nat", "int") or kind in _INT_BOUNDS:
            if not isinstance(value, int) or isinstance(value, bool): raise CandidEncodeError("%s must be int" % path)
            if kind == "nat" and value < 0: raise CandidEncodeError("%s must be non-negative" % path)
            if kind in _INT_BOUNDS and not (_INT_BOUNDS[kind][0] <= value <= _INT_BOUNDS[kind][1]):
                raise CandidEncodeError("%s is outside %s bounds" % (path, kind))
        elif kind in ("float32", "float64"):
            if not isinstance(value, (int, float)) or isinstance(value, bool): raise CandidEncodeError("%s must be numeric" % path)
        elif kind == "opt":
            if value is not None: self.inner.validate(value, path)
        elif kind == "vec":
            if self.inner.kind == "nat8" and isinstance(value, (bytes, bytearray)): return value
            if not isinstance(value, (list, tuple)): raise CandidEncodeError("%s must be a vector" % path)
            for index, item in enumerate(value): self.inner.validate(item, "%s[%d]" % (path, index))
        elif kind == "record":
            if not isinstance(value, dict): raise CandidEncodeError("%s must be a record" % path)
            expected = dict(self.fields)
            unknown = sorted(set(value) - set(expected))
            missing = sorted(name for name, spec in self.fields if name not in value and spec.kind != "opt")
            if unknown: raise CandidEncodeError("%s has unknown fields: %s" % (path, ", ".join(unknown)))
            if missing: raise CandidEncodeError("%s is missing fields: %s" % (path, ", ".join(missing)))
            for name, spec in self.fields:
                if name in value: spec.validate(value[name], "%s.%s" % (path, name))
        elif kind == "variant":
            if not isinstance(value, dict) or len(value) != 1: raise CandidEncodeError("%s variant must have exactly one field" % path)
            name = next(iter(value)); choices = dict(self.fields)
            if name not in choices: raise CandidEncodeError("%s has unknown variant %s" % (path, name))
            choices[name].validate(value[name], "%s.%s" % (path, name))
        else:
            raise CandidEncodeError("unsupported Candid type %s at %s" % (kind, path))
        return value


@dataclass(frozen=True)
class MethodSpec:
    name: str
    args: tuple = ()
    returns: tuple = ()
    mode: str = "update"

    def __post_init__(self):
        if (not isinstance(self.name, str) or not self.name or len(self.name) > 128 or
                any(ord(char) < 32 or ord(char) == 127 for char in self.name)):
            raise ValueError("method name must be 1-128 printable characters")
        if self.mode not in ("update", "query", "oneway"):
            raise ValueError("method mode must be update, query, or oneway")

    def validate_args(self, args):
        if len(args) != len(self.args):
            raise CandidEncodeError("%s expects %d argument(s), got %d" % (self.name, len(self.args), len(args)))
        for index, (spec, value) in enumerate(zip(self.args, args)):
            spec.validate(value, "%s argument %d" % (self.name, index + 1))


class ServiceSpec:
    def __init__(self, methods, name="Service"):
        self.name = str(name)
        items = methods.items() if isinstance(methods, dict) else ((method.name, method) for method in methods)
        self.methods = tuple(sorted(items))
        if any(name != method.name for name, method in self.methods):
            raise ValueError("service method keys must match MethodSpec names")

    def method(self, name):
        for method_name, spec in self.methods:
            if method_name == name: return spec
        raise KeyError(name)
