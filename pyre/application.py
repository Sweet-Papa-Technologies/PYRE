"""The PYRE App: Flask-flavored routing over ICP's HTTP gateway interface."""

import json as _json

from pyre._runtime import ctx
from pyre.errors import BadRequest, PyreError
from pyre.http_types import Request, Response, coerce_response
from pyre.outcall import is_pumpable, pump, pump_sync
from pyre.routing import Router
from pyre.validation import ValidationError

# Sentinel: this request must be re-issued as an update call
# (http_request answers with upgrade=True).
UPGRADE = object()


class App:
    def __init__(self, debug=False):
        self.router = Router()
        self.debug = debug
        # response certification (v2): built lazily on first certified route
        # or first recertify(); active only once set_certified_data succeeds
        self.certification = None
        self._certification_active = False
        self._before_hooks = []
        self._after_hooks = []
        self._error_handlers = {}
        self.cors = None

    # -- route registration --------------------------------------------------

    def route(self, path, methods=("GET",), update=None, certified=False):
        def decorator(handler):
            for method in methods:
                self.router.add(method, path, handler, update=update, certified=certified)
            return handler

        return decorator

    def get(self, path, update=None, certified=False):
        return self.route(path, methods=("GET",), update=update, certified=certified)

    def post(self, path, update=None):
        return self.route(path, methods=("POST",), update=update)

    def put(self, path, update=None):
        return self.route(path, methods=("PUT",), update=update)

    def delete(self, path, update=None):
        return self.route(path, methods=("DELETE",), update=update)

    # -- middleware / hooks ----------------------------------------------------

    def before_request(self, fn):
        """Runs before every handler. Return None to continue, or a
        Response (or dict/str) to short-circuit the request."""
        self._before_hooks.append(fn)
        return fn

    def after_request(self, fn):
        """Runs after every handler with (request, response); must return
        the (possibly replaced) response.

        Certified routes run hooks at CERTIFICATION time, not at serve time
        — the served bytes must match the certified snapshot exactly."""
        self._after_hooks.append(fn)
        return fn

    def errorhandler(self, status):
        """Register a custom handler for a framework-generated error status
        (404, 405, 400, 500). Called with (request, info_dict); returns a
        Response/dict/str."""

        def decorator(fn):
            self._error_handlers[int(status)] = fn
            return fn

        return decorator

    def enable_cors(self, origins="*", **kwargs):
        from pyre.cors import CorsConfig

        self.cors = CorsConfig(origins=origins, **kwargs)
        return self.cors

    # -- shared dispatch pieces --------------------------------------------------

    def _error_payload(self, status, payload, request):
        handler = self._error_handlers.get(status)
        if handler is not None:
            try:
                rv = coerce_response(handler(request, payload))
                if rv is not None:
                    rv.status = rv.status if rv.status != 200 else status
                    return rv
            except Exception:  # noqa: BLE001 — a broken error handler falls through
                pass
        return Response.json(payload, status=status)

    def _lookup(self, request):
        """Returns (route, error_response). Fills request.path_params."""
        route, params, allowed = self.router.match(request.method, request.path)
        if route is None:
            if allowed:
                response = self._error_payload(
                    405,
                    {"error": "method not allowed", "allowed": allowed},
                    request,
                )
                if not response._has_header("allow"):
                    response.headers.append(("allow", ", ".join(allowed)))
                return None, response
            return None, self._error_payload(
                404, {"error": "not found", "path": request.path}, request
            )
        request.path_params = params
        return route, None

    def _error_response(self, exc, request):
        if isinstance(exc, ValidationError):
            return self._error_payload(
                400, {"error": "validation failed", "fields": exc.fields}, request
            )
        if isinstance(exc, BadRequest):
            return self._error_payload(
                400, {"error": "bad request", "message": str(exc)}, request
            )
        payload = {"error": "internal server error", "message": str(exc)}
        if self.debug:
            import traceback

            payload["traceback"] = traceback.format_exc()
        return self._error_payload(500, payload, request)

    def _finish(self, rv, request):
        response = coerce_response(rv)
        if response is None:
            return self._error_response(
                PyreError(
                    "handler returned %s; expected Response, dict, list, str or bytes"
                    % type(rv).__name__
                ),
                request,
            )
        return response

    def _run_before(self, request):
        for hook in self._before_hooks:
            rv = hook(request)
            if rv is not None:
                return coerce_response(rv)
        return None

    def _run_after(self, request, response):
        for hook in self._after_hooks:
            rv = hook(request, response)
            replaced = coerce_response(rv)
            if replaced is None:
                raise PyreError(
                    "after_request hook %r must return the response"
                    % getattr(hook, "__name__", hook)
                )
            response = replaced
        return response

    def _apply_cors(self, request, response):
        if self.cors is not None and response is not None:
            response.headers.extend(self.cors.response_headers(request))
        return response

    def _preflight(self, request):
        """CORS preflight. Returns a Response or None (not a preflight)."""
        if self.cors is None or request.method != "OPTIONS":
            return None
        _, _, allowed = self.router.match("OPTIONS", request.path)
        headers = self.cors.preflight_headers(request, allowed or ["GET", "POST", "PUT", "DELETE"])
        if headers is None:
            return Response(b"", status=403)
        return Response(b"", status=204, headers=headers)

    def _execute_sync(self, route, request):
        """before hooks → handler → after hooks, synchronously (no outcalls)."""
        short_circuit = self._run_before(request)
        if short_circuit is not None:
            return short_circuit
        rv = route.handler(request)
        if is_pumpable(rv):
            rv.close()
            raise PyreError(
                "handler for %s %s is async/generator but ran in a synchronous "
                "context; mark it update=True" % (route.method, route.path)
            )
        response = self._finish(rv, request)
        return self._run_after(request, response)

    # -- query path (http_request) --------------------------------------------

    def handle_query(self, request):
        """Run a query-context dispatch. Returns Response or UPGRADE.

        Non-2xx results are answered with UPGRADE: uncertified error
        responses fail gateway verification, while update responses are
        consensus-certified. Errors cost an update round; happy-path GETs
        stay fast queries.
        """
        preflight = self._preflight(request)
        if preflight is not None:
            return self._apply_cors(request, preflight)
        route, error = self._lookup(request)
        if error is not None:
            return UPGRADE  # 404/405 served certified via update
        if route.update:
            return UPGRADE
        if route.certified and self.certification is not None:
            snapshot = self.certification.responses.get(request.path)
            if snapshot is not None:
                # Serve the exact bytes committed to the hash tree. Hooks ran
                # at certification time; only uncertified headers (CORS) are
                # added here, on a copy — never mutate the snapshot.
                copy = Response(snapshot.body, status=snapshot.status,
                                headers=list(snapshot.headers))
                return self._apply_cors(request, copy)
        ctx.in_query = True
        try:
            response = self._execute_sync(route, request)
        except Exception as e:  # noqa: BLE001 — handler errors become 500s
            response = self._error_response(e, request)
        finally:
            ctx.in_query = False
        if response.status >= 300:
            return UPGRADE  # non-2xx from a query handler: re-serve certified
        return self._apply_cors(request, response)

    # -- update path (http_request_update) -------------------------------------

    def handle_update(self, request):
        """Generator for the Kybra update method: `yield from app.handle_update(req)`."""
        preflight = self._preflight(request)
        if preflight is not None:
            return self._apply_cors(request, preflight)
        route, error = self._lookup(request)
        if error is not None:
            return self._apply_cors(request, error)
        try:
            short_circuit = self._run_before(request)
            if short_circuit is not None:
                return self._apply_cors(request, short_circuit)
            rv = route.handler(request)
            if is_pumpable(rv):
                rv = yield from pump(rv)
            response = self._finish(rv, request)
            response = self._run_after(request, response)
        except Exception as e:  # noqa: BLE001
            response = self._error_response(e, request)
        return self._apply_cors(request, response)

    # -- certification (response verification v2) -------------------------------

    def has_certified_routes(self):
        return any(route.certified for route in self.router.routes)

    def recertify(self):
        """Re-render every certified route, rebuild the hash tree, and commit
        its root to certified data.

        Must run in update context (init / post_upgrade / update calls); the
        gateway calls this automatically after every update dispatch. Runs
        the full hook chain so snapshots match live serving. Certified routes
        MUST produce a 2xx Response here — anything else raises PyreError.
        """
        import pyre.certification

        if self.certification is None:
            self.certification = pyre.certification.CertifiedStore()
        for route in self.router.routes:
            if not route.certified:
                continue
            ctx.in_query = True
            try:
                response = self._execute_sync(route, Request("GET", route.path))
            finally:
                ctx.in_query = False
            if not (200 <= response.status < 300):
                raise PyreError(
                    "certified route GET %s must return a 2xx Response at "
                    "certification time (got status %d)" % (route.path, response.status)
                )
            self.certification.put(route.path, response)
        root = self.certification.rebuild()
        self._certification_active = pyre.certification.set_certified_data(root)
        return root

    # -- dev path ---------------------------------------------------------------

    def handle_dev(self, request, resolve_outcall):
        """Synchronous dispatch for `pyre dev`, honoring query restrictions."""
        preflight = self._preflight(request)
        if preflight is not None:
            return self._apply_cors(request, preflight)
        route, error = self._lookup(request)
        if error is not None:
            return self._apply_cors(request, error)
        ctx.in_query = not route.update
        try:
            short_circuit = self._run_before(request)
            if short_circuit is not None:
                return self._apply_cors(request, short_circuit)
            rv = route.handler(request)
            if is_pumpable(rv):
                rv = pump_sync(rv, resolve_outcall)
            response = self._finish(rv, request)
            response = self._run_after(request, response)
        except Exception as e:  # noqa: BLE001
            response = self._error_response(e, request)
        finally:
            ctx.in_query = False
        return self._apply_cors(request, response)
