"""CORS support (WS-A): response headers + preflight OPTIONS handling.

    app = App()
    app.enable_cors(origins=["https://myapp.example"])   # or origins="*"

Preflight OPTIONS requests are answered directly by the framework (as fast
query calls — they never upgrade), and matching CORS headers are attached
to every response, including certified ones (CORS headers are not part of
the certified header set, so they never affect certification).
"""


class CorsConfig:
    def __init__(self, origins="*", methods=None, headers=("content-type", "authorization"),
                 expose_headers=(), max_age=86400, allow_credentials=False):
        if isinstance(origins, str):
            origins = [origins]
        self.origins = list(origins)
        self.allow_any = "*" in self.origins
        self.methods = list(methods) if methods else None  # None → per-route
        self.headers = list(headers)
        self.expose_headers = list(expose_headers)
        self.max_age = int(max_age)
        self.allow_credentials = bool(allow_credentials)
        if self.allow_credentials and self.allow_any:
            raise ValueError(
                "CORS: allow_credentials=True cannot be combined with origins='*' "
                "(browsers reject it); list the origins explicitly"
            )

    def _origin_value(self, request):
        origin = request.headers.get("origin")
        if self.allow_any:
            return "*"
        if origin and origin in self.origins:
            return origin
        return None

    def response_headers(self, request):
        """Headers to append to a normal response."""
        value = self._origin_value(request)
        if value is None:
            return []
        out = [("access-control-allow-origin", value)]
        if not self.allow_any:
            out.append(("vary", "origin"))
        if self.expose_headers:
            out.append(("access-control-expose-headers", ", ".join(self.expose_headers)))
        if self.allow_credentials:
            out.append(("access-control-allow-credentials", "true"))
        return out

    def preflight_headers(self, request, allowed_methods):
        value = self._origin_value(request)
        if value is None:
            return None
        methods = self.methods if self.methods else allowed_methods
        out = [
            ("access-control-allow-origin", value),
            ("access-control-allow-methods", ", ".join(sorted(set(m.upper() for m in methods)))),
            ("access-control-allow-headers", ", ".join(self.headers)),
            ("access-control-max-age", str(self.max_age)),
        ]
        if not self.allow_any:
            out.append(("vary", "origin"))
        if self.allow_credentials:
            out.append(("access-control-allow-credentials", "true"))
        return out
