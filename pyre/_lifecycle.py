"""Deterministic lifecycle restoration for PYRE applications."""

from pyre import log


class LifecycleError(RuntimeError):
    pass


_hooks = {}


def register(name, callback, order=100, required=True):
    if (not isinstance(name, str) or not name or len(name) > 128 or
            any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise ValueError("lifecycle hook name must be 1-128 printable characters")
    if name in _hooks:
        raise LifecycleError("lifecycle hook %r is already registered" % name)
    if not callable(callback):
        raise TypeError("lifecycle hook callback must be callable")
    _hooks[name] = (int(order), callback, bool(required))
    return callback


def unregister(name):
    return _hooks.pop(name, None) is not None


def clear_hooks():
    _hooks.clear()


def _emit(level, event, **fields):
    writer = getattr(log, level, None)
    if writer is not None:
        writer(event, **fields)


def _run_hooks(phase):
    for name, (order, callback, required) in sorted(
        _hooks.items(), key=lambda item: (item[1][0], item[0])
    ):
        _emit("info", "lifecycle.hook_started", hook=name, phase=phase, order=order)
        try:
            callback()
        except Exception as exc:
            _emit("error", "lifecycle.hook_failed", hook=name, phase=phase, error=str(exc)[:256])
            if required:
                raise
        else:
            _emit("info", "lifecycle.hook_completed", hook=name, phase=phase)


def run_init(app):
    app.recertify()
    _run_hooks("init")


def run_post_upgrade(app):
    app.recertify()
    _run_hooks("post_upgrade")
