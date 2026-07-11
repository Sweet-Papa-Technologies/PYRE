"""Injectable boundary between PYRE features and Internet Computer APIs."""

from pyre._runtime import ctx, in_canister


class PlatformUnavailable(RuntimeError):
    """Raised when an IC-only operation is used without an installed adapter."""
    code = "PYRE-PLATFORM-UNAVAILABLE"


class _HostAdapter:
    def _unavailable(self, operation):
        raise PlatformUnavailable(
            "%s is unavailable on the host; install a test platform adapter" % operation
        )

    def now_ns(self):
        self._unavailable("now_ns")

    def set_timer(self, delay_ns, callback):
        self._unavailable("set_timer")

    def clear_timer(self, handle):
        self._unavailable("clear_timer")

    def call_raw(self, canister_id, method, payload, cycles=0):
        self._unavailable("call_raw")

    def notify_raw(self, canister_id, method, payload, cycles=0):
        self._unavailable("notify_raw")

    def candid_encode(self, text):
        self._unavailable("candid_encode")

    def candid_decode(self, payload):
        self._unavailable("candid_decode")


class _CanisterAdapter:
    """Thin Kybra 0.7.1 adapter; imports occur only under RustPython."""

    @staticmethod
    def _ic():
        from kybra import ic
        return ic

    def now_ns(self):
        return int(self._ic().time())

    def set_timer(self, delay_ns, callback):
        # Kybra Duration is represented as integer nanoseconds.
        return self._ic().set_timer(int(delay_ns), callback)

    def clear_timer(self, handle):
        return self._ic().clear_timer(handle)

    def call_raw(self, canister_id, method, payload, cycles=0):
        from kybra import Principal
        return self._ic().call_raw(
            Principal.from_str(canister_id), str(method), bytes(payload), int(cycles)
        )

    def notify_raw(self, canister_id, method, payload, cycles=0):
        from kybra import Principal
        return self._ic().notify_raw(
            Principal.from_str(canister_id), str(method), bytes(payload), int(cycles)
        )

    def candid_encode(self, text):
        return self._ic().candid_encode(str(text))

    def candid_decode(self, payload):
        return self._ic().candid_decode(bytes(payload))


_adapter = _CanisterAdapter() if in_canister() else _HostAdapter()


def install_adapter(adapter):
    """Install *adapter* and return the previous adapter (primarily for tests)."""
    global _adapter
    previous = _adapter
    _adapter = adapter
    return previous


def reset_adapter():
    global _adapter
    _adapter = _HostAdapter()


def dispatch_context():
    return ctx


def now_ns():
    return _adapter.now_ns()


def set_timer(delay_ns, callback):
    return _adapter.set_timer(delay_ns, callback)


def clear_timer(handle):
    return _adapter.clear_timer(handle)


def call_raw(canister_id, method, payload, cycles=0):
    return _adapter.call_raw(canister_id, method, payload, cycles=cycles)


def notify_raw(canister_id, method, payload, cycles=0):
    return _adapter.notify_raw(canister_id, method, payload, cycles=cycles)


def candid_encode(text):
    return _adapter.candid_encode(text)


def candid_decode(payload):
    return _adapter.candid_decode(payload)
