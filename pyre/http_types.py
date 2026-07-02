"""Request / Response objects shared by the canister gateway and `pyre dev`.

Pure Python 3.10, stdlib-optional: usable both under RustPython inside the
canister and under host CPython.
"""

import json as _json

from pyre.errors import BadRequest

try:
    from urllib.parse import unquote_plus as _unquote_plus
except ImportError:  # minimal fallback if the runtime lacks urllib.parse

    def _unquote_plus(s):
        s = s.replace("+", " ")
        out = []
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == "%" and i + 2 < len(s) + 1 and len(s) >= i + 3:
                try:
                    out.append(chr(int(s[i + 1 : i + 3], 16)))
                    i += 3
                    continue
                except ValueError:
                    pass
            out.append(ch)
            i += 1
        return "".join(out)


def parse_query_string(qs):
    """Parse 'a=1&b=2&b=3' into {'a': ['1'], 'b': ['2', '3']}."""
    result = {}
    if not qs:
        return result
    for part in qs.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        result.setdefault(_unquote_plus(key), []).append(_unquote_plus(value))
    return result


class Request:
    """An inbound HTTP request as seen by a PYRE handler."""

    def __init__(self, method, path, headers=None, query_string="", body=b"", path_params=None):
        self.method = method.upper()
        self.path = path or "/"
        # header names are case-insensitive; store lowercased
        self.headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        self.query_string = query_string
        self.query_list = parse_query_string(query_string)
        # convenience: first value per key
        self.query = {k: v[0] for k, v in self.query_list.items()}
        self.body = body if isinstance(body, (bytes, bytearray)) else str(body or "").encode("utf-8")
        self.path_params = path_params or {}
        # Caller principal string; set by the canister gateway (anonymous
        # "2vxsx-fae" for plain HTTP traffic), None in dev/tests.
        self.caller = None

    def json(self):
        """Parse the request body as JSON. Raises BadRequest (→ 400) if invalid."""
        if not self.body:
            raise BadRequest("request body is empty; expected JSON")
        try:
            return _json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise BadRequest("request body is not valid JSON: %s" % e)

    def text(self):
        return self.body.decode("utf-8")

    def __repr__(self):
        return "<Request %s %s>" % (self.method, self.path)


class Response:
    """An HTTP response returned by a PYRE handler."""

    def __init__(self, body=b"", status=200, headers=None, content_type=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.body = bytes(body)
        self.status = int(status)
        # keep insertion order; list of (name, value)
        if headers is None:
            self.headers = []
        elif isinstance(headers, dict):
            self.headers = [(str(k), str(v)) for k, v in headers.items()]
        else:
            self.headers = [(str(k), str(v)) for k, v in headers]
        if content_type is not None and not self._has_header("content-type"):
            self.headers.append(("content-type", content_type))

    def _has_header(self, name):
        name = name.lower()
        return any(k.lower() == name for k, _ in self.headers)

    @classmethod
    def json(cls, obj, status=200, headers=None):
        return cls(
            _json.dumps(obj),
            status=status,
            headers=headers,
            content_type="application/json",
        )

    @classmethod
    def text(cls, s, status=200, headers=None):
        return cls(s, status=status, headers=headers, content_type="text/plain; charset=utf-8")

    def __repr__(self):
        return "<Response %s (%d bytes)>" % (self.status, len(self.body))


def coerce_response(rv):
    """Allow handlers to return Response, dict/list (→ JSON), or str (→ text)."""
    if isinstance(rv, Response):
        return rv
    if isinstance(rv, (dict, list)):
        return Response.json(rv)
    if isinstance(rv, str):
        return Response.text(rv)
    if isinstance(rv, (bytes, bytearray)):
        return Response(bytes(rv), content_type="application/octet-stream")
    return None
