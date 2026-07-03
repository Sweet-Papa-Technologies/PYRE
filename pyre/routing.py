"""Flask-style routing: path templates like '/items/{id}'."""

import re

# Detect generator/coroutine handlers via co_flags — but the flag BITS are
# interpreter-specific (RustPython's differ from CPython's, and hardcoding
# CPython's 0x20/0x80 misclassified plain functions inside the canister).
# Probe the running interpreter once: whatever bits distinguish a generator
# and a coroutine from a plain function here are the bits we test for.


def _probe_async_bits():
    def _plain():
        pass

    def _gen():
        yield

    async def _coro():
        pass

    try:
        plain_flags = _plain.__code__.co_flags
        gen_bits = _gen.__code__.co_flags & ~plain_flags
        coro_bits = _coro.__code__.co_flags & ~plain_flags
        return gen_bits | coro_bits
    except AttributeError:
        return 0


_ASYNC_CO_BITS = _probe_async_bits()


def is_async_handler(fn):
    """True if fn is a generator function or an `async def` coroutine function.

    Falls back to False if the interpreter exposes no distinguishing bits —
    explicit update=True still works, and outcalls from query context raise
    a clear OutcallInQueryContext at runtime.
    """
    if not _ASYNC_CO_BITS:
        return False
    code = getattr(fn, "__code__", None)
    flags = getattr(code, "co_flags", 0)
    return bool(flags & _ASYNC_CO_BITS)


_PARAM_SEGMENT = re.compile(r"^\{([a-zA-Z_][a-zA-Z0-9_]*)\}$")

# Catch-all tail: '/{name:path}' — matches the REST of the URL (slashes
# included, may be empty). Only valid as the final segment. Routes with a
# catch-all are matched at LOWER priority than every other route, so a
# static-file catch-all can never shadow API routes (see Router.match).
_CATCHALL_SEGMENT = re.compile(r"^\{([a-zA-Z_][a-zA-Z0-9_]*):path\}$")

# Methods whose default execution context is update (they imply writes).
_UPDATE_BY_DEFAULT = ("POST", "PUT", "DELETE", "PATCH")


def is_catchall_path(path):
    """True if the route path ends in a '{name:path}' catch-all segment."""
    return bool(_CATCHALL_SEGMENT.match(path.split("/")[-1]))


def compile_path(path):
    """'/items/{id}' → compiled regex with named groups."""
    if not path.startswith("/"):
        raise ValueError("route path must start with '/': %r" % path)
    parts = path.split("/")
    pattern = []
    for i, part in enumerate(parts):
        catchall = _CATCHALL_SEGMENT.match(part)
        if catchall:
            if i != len(parts) - 1:
                raise ValueError(
                    "catch-all '{%s:path}' must be the last segment: %r"
                    % (catchall.group(1), path)
                )
            pattern.append("(?P<%s>.*)" % catchall.group(1))
            continue
        m = _PARAM_SEGMENT.match(part)
        if m:
            pattern.append("(?P<%s>[^/]+)" % m.group(1))
        else:
            pattern.append(re.escape(part))
    return re.compile("^" + "/".join(pattern) + "$")


class Route:
    def __init__(self, method, path, handler, update=None, certified=False):
        self.method = method.upper()
        self.path = path
        self.handler = handler
        self.regex = compile_path(path)
        self.catch_all = is_catchall_path(path)
        if update is None:
            # Auto-promotion (requirements §6.1):
            #  - generator / async handlers need update context (outcalls)
            #  - POST/PUT/DELETE/PATCH imply state writes
            update = self.method in _UPDATE_BY_DEFAULT or is_async_handler(handler)
        self.update = bool(update)
        if certified:
            if self.method != "GET":
                raise ValueError("certified=True requires a GET route: %s" % path)
            if "{" in path:
                raise ValueError(
                    "certified=True requires a static path (no {params}): %s" % path
                )
            if self.update:
                raise ValueError(
                    "certified=True routes are query routes; update=True conflicts: %s"
                    % path
                )
        self.certified = bool(certified)

    def match(self, path):
        m = self.regex.match(path)
        return m.groupdict() if m else None

    def __repr__(self):
        kind = "update" if self.update else "query"
        return "<Route %s %s (%s)>" % (self.method, self.path, kind)


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, path, handler, update=None, certified=False):
        route = Route(method, path, handler, update=update, certified=certified)
        self.routes.append(route)
        return route

    def match(self, method, path):
        """Returns (route, path_params, allowed_methods).

        route is None on no match; allowed_methods is non-empty when the
        path exists under other methods (→ 405).

        Catch-all routes ('/{tail:path}') match at LOWER priority than every
        exact/param route regardless of registration order, so mounting a
        static-file catch-all never shadows API routes on the same app.
        """
        method = method.upper()
        allowed = []
        fallback = fallback_params = None
        for route in self.routes:
            params = route.match(path)
            if params is None:
                continue
            if route.method == method:
                if route.catch_all:
                    if fallback is None:
                        fallback, fallback_params = route, params
                    continue
                return route, params, []
            allowed.append(route.method)
        if fallback is not None:
            return fallback, fallback_params, []
        return None, None, sorted(set(allowed))
