"""Bounded host-side parser for the Candid subset emitted by PYRE codegen."""

import re
import json

from pyre.candid import MethodSpec, ServiceSpec, TypeSpec

MAX_SOURCE_BYTES = 1_000_000
MAX_DEPTH = 64
MAX_FIELDS = 10_000
MAX_ALIAS_DEPTH = 64
_TOKEN = re.compile(r'\s+|//[^\n]*|/\*.*?\*/|->|[A-Za-z_][A-Za-z0-9_]*|[0-9]+|"(?:\\.|[^"\\])*"|[{}():;,=]', re.S)
_PRIMITIVES = {"null", "bool", "text", "principal", "blob", "nat", "int", "nat8", "nat16", "nat32", "nat64", "int8", "int16", "int32", "int64", "float32", "float64"}


class CandidSyntaxError(ValueError):
    code = "PYRE-CANDID-SYNTAX"
    def __init__(self, source, offset, token, expected):
        line = source.count("\n", 0, offset) + 1
        start = source.rfind("\n", 0, offset) + 1
        column = offset - start + 1
        self.line, self.column, self.token, self.expected = line, column, token, expected
        super().__init__("line %d, column %d: got %r; expected %s" % (line, column, token, expected))


def _tokens(source):
    result, offset = [], 0
    while offset < len(source):
        match = _TOKEN.match(source, offset)
        if not match: raise CandidSyntaxError(source, offset, source[offset:offset + 16], "Candid token")
        text = match.group(0); start = offset; offset = match.end()
        if text.isspace() or text.startswith(("//", "/*")): continue
        result.append((text, start))
    result.append(("<eof>", len(source)))
    return result


class Parser:
    def __init__(self, source, max_source_bytes=MAX_SOURCE_BYTES, max_depth=MAX_DEPTH,
                 max_fields=MAX_FIELDS, max_alias_depth=MAX_ALIAS_DEPTH):
        if len(source.encode("utf-8")) > max_source_bytes: raise ValueError("Candid source exceeds %d bytes" % max_source_bytes)
        self.source, self.tokens, self.index = source, _tokens(source), 0
        self.aliases, self.max_depth, self.max_fields, self.max_alias_depth = {}, max_depth, max_fields, max_alias_depth
        self.field_count = 0

    def peek(self): return self.tokens[self.index][0]
    def take(self): token = self.tokens[self.index]; self.index += 1; return token[0]
    def expect(self, expected):
        if self.peek() != expected:
            token, offset = self.tokens[self.index]; raise CandidSyntaxError(self.source, offset, token, expected)
        return self.take()
    def identifier(self):
        token, offset = self.tokens[self.index]
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", token): raise CandidSyntaxError(self.source, offset, token, "identifier")
        self.index += 1; return token

    def parse(self):
        service = None
        while self.peek() == "type":
            self.take(); name = self.identifier(); self.expect("="); self.aliases[name] = self.type_expr(0); self.expect(";")
        if self.peek() == "service":
            self.take()
            if self.peek() not in (":", "{"): self.identifier()
            if self.peek() == "=": self.take()
            self.expect(":"); service = self.service()
            if self.peek() == ";": self.take()
        if self.peek() != "<eof>":
            token, offset = self.tokens[self.index]; raise CandidSyntaxError(self.source, offset, token, "type or service declaration")
        if service is None: raise CandidSyntaxError(self.source, len(self.source), "<eof>", "service declaration")
        methods = []
        for _name, method in service.methods:
            methods.append(MethodSpec(
                method.name,
                tuple(self.resolve_type(item, ()) for item in method.args),
                tuple(self.resolve_type(item, ()) for item in method.returns),
                method.mode,
            ))
        return ServiceSpec(methods, name=service.name)

    def type_expr(self, depth):
        if depth > self.max_depth: raise ValueError("Candid nesting exceeds %d" % self.max_depth)
        token = self.take()
        if token in _PRIMITIVES: return TypeSpec(token)
        if token in ("opt", "vec"): return TypeSpec(token, inner=self.type_expr(depth + 1))
        if token in ("record", "variant"):
            self.expect("{"); fields = {}
            while self.peek() != "}":
                name = self.take()
                if name.startswith('"'): name = bytes(name[1:-1], "utf-8").decode("unicode_escape")
                self.expect(":"); fields[name] = self.type_expr(depth + 1); self.field_count += 1
                if self.field_count > self.max_fields: raise ValueError("Candid field count exceeds %d" % self.max_fields)
                if self.peek() in (";", ","): self.take()
                elif self.peek() != "}": self.expect(";")
            self.take(); return TypeSpec.record(fields) if token == "record" else TypeSpec.variant(fields)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", token):
            return TypeSpec("alias", inner=token)
        offset = self.tokens[self.index - 1][1]; raise CandidSyntaxError(self.source, offset, token, "Candid type")

    def resolve_alias(self, name, trail):
        if name not in self.aliases:
            raise ValueError("unknown Candid type alias %s" % name)
        if name in trail: raise ValueError("recursive alias cycle: %s" % " -> ".join(trail + (name,)))
        if len(trail) >= self.max_alias_depth: raise ValueError("alias depth exceeds %d" % self.max_alias_depth)
        return self.resolve_type(self.aliases[name], trail + (name,))

    def resolve_type(self, spec, trail):
        if spec.kind == "alias": return self.resolve_alias(spec.inner, trail)
        if spec.kind in ("opt", "vec"):
            return TypeSpec(spec.kind, inner=self.resolve_type(spec.inner, trail))
        if spec.kind in ("record", "variant"):
            fields = {name: self.resolve_type(value, trail) for name, value in spec.fields}
            return TypeSpec.record(fields) if spec.kind == "record" else TypeSpec.variant(fields)
        return spec

    def type_list(self):
        self.expect("("); values = []
        while self.peek() != ")":
            values.append(self.type_expr(0))
            if self.peek() == ",": self.take()
            elif self.peek() != ")": self.expect(",")
        self.take(); return tuple(values)

    def service(self):
        self.expect("{"); methods = []
        while self.peek() != "}":
            name = self.take()
            if name.startswith('"'): name = json.loads(name)
            self.expect(":"); args = self.type_list(); self.expect("->"); returns = self.type_list()
            mode = "update"
            if self.peek() in ("query", "oneway"): mode = self.take()
            methods.append(MethodSpec(name, args, returns, mode)); self.field_count += 1
            if self.peek() in (";", ","): self.take()
            elif self.peek() != "}": self.expect(";")
        self.take(); return ServiceSpec(methods)


def parse(source, **limits):
    return Parser(source, **limits).parse()
