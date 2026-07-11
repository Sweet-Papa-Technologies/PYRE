"""Upgrade-safe, persistent background work for Internet Computer canisters.

Execution is at-least-once in the presence of traps/upgrades, never exactly
once. Callbacks should therefore be idempotent. Intervals are minimum targets.
"""

import hashlib
import inspect
import re

from pyre import kv, log
from pyre import _platform as platform
from pyre._namespace import framework_key, list_prefix
from pyre._runtime import ctx, in_canister
from pyre.outcall import is_pumpable, pump

SCHEMA = 1
MAX_DUE_PER_WAKE = 25
MAX_ERROR_CHARS = 256
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_definitions = {}
_aliases = {}
_timer_handle = None
_supervisor_running = False


class TaskError(RuntimeError):
    code = "PYRE-TASK-ERROR"


class DuplicateTask(TaskError):
    code = "PYRE-TASK-DUPLICATE"


class UnknownTask(TaskError):
    code = "PYRE-TASK-UNKNOWN"


class TaskState(dict):
    """Public snapshot; internal stable keys are deliberately absent."""


def _validate_name(name):
    if not isinstance(name, str) or not _NAME.match(name):
        raise ValueError("task name must match %s" % _NAME.pattern)
    return name


def _key(name):
    return framework_key("tasks", SCHEMA, "record", name)


def _definition_hash(name, kind, schedule, overlap, catch_up):
    text = "%s|%s|%s|%s|%s" % (name, kind, schedule, overlap, catch_up)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record(definition, now):
    name = definition["name"]
    once = definition["kind"] == "once"
    schedule = definition["schedule_ns"]
    return {
        "schema": SCHEMA,
        "name": name,
        "kind": definition["kind"],
        "interval_ns": None if once else schedule,
        "run_at_ns": now + schedule if once else None,
        "next_run_at_ns": now + schedule,
        "enabled": True,
        "overlap": definition["overlap"],
        "catch_up": definition["catch_up"],
        "state": "scheduled",
        "last_started_at_ns": None,
        "last_finished_at_ns": None,
        "last_success_at_ns": None,
        "run_count": 0,
        "failure_count": 0,
        "last_error": None,
        "definition_hash": definition["definition_hash"],
        "queued": False,
        "active_runs": 0,
    }


def _save(record):
    kv.set(_key(record["name"]), record)


def _load(name):
    record = kv.get(_key(_validate_name(name)))
    if record is None:
        raise UnknownTask("unknown task %r" % name)
    if record.get("schema") != SCHEMA:
        raise TaskError("unsupported task schema %r for %s" % (record.get("schema"), name))
    return record


def _decorate(kind, seconds, name, overlap, catch_up):
    if not isinstance(seconds, (int, float)) or seconds < 0:
        raise ValueError("seconds must be a non-negative number")
    if kind == "interval" and seconds <= 0:
        raise ValueError("interval seconds must be greater than zero")
    if overlap not in ("skip", "queue_one", "allow"):
        raise ValueError("overlap must be skip, queue_one, or allow")
    if catch_up not in ("skip", "run_once"):
        raise ValueError("catch_up must be skip or run_once")

    def decorator(callback):
        if _supervisor_running:
            raise TaskError("tasks cannot be registered while the supervisor is running")
        task_name = _validate_name(name or "%s.%s" % (callback.__module__, callback.__name__))
        if task_name in _definitions:
            raise DuplicateTask("task %r is already registered" % task_name)
        schedule_ns = int(seconds * 1_000_000_000)
        definition = {
            "name": task_name, "kind": kind, "schedule_ns": schedule_ns,
            "overlap": overlap, "catch_up": catch_up, "callback": callback,
        }
        definition["definition_hash"] = _definition_hash(task_name, kind, schedule_ns, overlap, catch_up)
        _definitions[task_name] = definition
        if in_canister():
            # Generated main.py imports application code before it can bind the
            # statically declared StableBTreeMap. Persist/schedule only from the
            # lifecycle hook after binding; timer handles are never durable.
            log.info("tasks.registered", task=task_name, kind=kind)
            return callback
        try:
            record = _load(task_name)
        except UnknownTask:
            record = _record(definition, platform.now_ns())
            _save(record)
        else:
            if record.get("definition_hash") != definition["definition_hash"]:
                record["kind"] = kind
                record["interval_ns"] = None if kind == "once" else schedule_ns
                record["run_at_ns"] = platform.now_ns() + schedule_ns if kind == "once" else None
                record["next_run_at_ns"] = platform.now_ns() + schedule_ns
                record["overlap"] = overlap
                record["catch_up"] = catch_up
            record["definition_hash"] = definition["definition_hash"]
            if record["state"] == "orphaned":
                record["state"] = "scheduled"
                record["enabled"] = True
            _save(record)
        log.info("tasks.registered", task=task_name, kind=kind)
        _schedule()
        return callback
    return decorator


def every(*, seconds, name=None, overlap="skip", catch_up="skip"):
    return _decorate("interval", seconds, name, overlap, catch_up)


def after(*, seconds, name=None, overlap="skip", catch_up="skip"):
    return _decorate("once", seconds, name, overlap, catch_up)


def cron(*args, **kwargs):
    raise NotImplementedError("five-field UTC cron is reserved for a later release")


def _schedule():
    global _timer_handle
    due = []
    for name in sorted(_definitions):
        try:
            record = _load(name)
        except UnknownTask:
            continue
        if record["enabled"] and record["state"] == "scheduled":
            due.append(record["next_run_at_ns"])
    if _timer_handle is not None:
        platform.clear_timer(_timer_handle)
        _timer_handle = None
    if due:
        delay = max(0, min(due) - platform.now_ns())
        _timer_handle = platform.set_timer(delay, _supervisor)


def _finish(record, success, error=None):
    # Reload so a suspended callback cannot overwrite pause/cancel/queue state
    # changed by another update while it awaited a remote call.
    record = _load(record["name"])
    now = platform.now_ns()
    record["active_runs"] = max(0, int(record.get("active_runs", 1)) - 1)
    record["last_finished_at_ns"] = now
    if success:
        record["last_success_at_ns"] = now
        record["last_error"] = None
    else:
        record["failure_count"] += 1
        record["last_error"] = str(error).replace("\r", " ").replace("\n", " ")[:MAX_ERROR_CHARS]
    if record.get("queued") and record["active_runs"] == 0:
        record["queued"] = False
        record["state"] = "scheduled"
        record["enabled"] = True
        record["next_run_at_ns"] = now
    elif record["state"] in ("paused", "cancelled", "orphaned") or not record["enabled"]:
        pass
    elif record["kind"] == "once":
        record["state"] = "completed" if success else "failed"
        record["enabled"] = False
    else:
        record["state"] = "scheduled"
        record["next_run_at_ns"] = now + record["interval_ns"]
    _save(record)


def _execute(name, force=False):
    record = _load(name)
    if record["state"] == "running" and not force:
        if record["overlap"] == "allow":
            pass
        else:
            if record["overlap"] == "queue_one":
                record["queued"] = True
                _save(record)
            log.info("tasks.skipped", task=name, reason="overlap")
            return False
    record["state"] = "running"
    record["active_runs"] = int(record.get("active_runs", 0)) + 1
    record["last_started_at_ns"] = platform.now_ns()
    record["run_count"] += 1
    _save(record)
    log.info("tasks.started", task=name, run_count=record["run_count"])
    try:
        result = _definitions[name]["callback"]()
        if inspect.isawaitable(result) or is_pumpable(result):
            def complete_async():
                try:
                    yield from pump(result)
                except Exception as exc:
                    _finish(record, False, exc)
                    log.error("tasks.failed", task=name, error=str(exc)[:MAX_ERROR_CHARS])
                    return False
                _finish(record, True)
                log.info("tasks.succeeded", task=name)
                return True
            return complete_async()
    except Exception as exc:
        _finish(record, False, exc)
        log.error("tasks.failed", task=name, error=str(exc)[:MAX_ERROR_CHARS])
        return False
    _finish(record, True)
    log.info("tasks.succeeded", task=name)
    return True


def _supervisor():
    global _supervisor_running, _timer_handle
    if _supervisor_running:
        return 0
    _supervisor_running = True
    _timer_handle = None
    count = 0
    try:
        now = platform.now_ns()
        names = []
        for name in sorted(_definitions):
            record = _load(name)
            if record["enabled"] and record["state"] == "scheduled" and record["next_run_at_ns"] <= now:
                names.append(name)
        for name in names[:MAX_DUE_PER_WAKE]:
            result = _execute(name)
            if is_pumpable(result):
                yield from result
            count += 1
    finally:
        _supervisor_running = False
        _schedule()
    return count


def pause(name):
    record = _load(name); record["enabled"] = False; record["state"] = "paused"; _save(record); _schedule(); return TaskState(record)


def resume(name):
    record = _load(name); record["enabled"] = True; record["state"] = "scheduled"; record["next_run_at_ns"] = platform.now_ns(); _save(record); _schedule(); return TaskState(record)


def cancel(name):
    record = _load(name); record["enabled"] = False; record["state"] = "cancelled"; _save(record); _schedule(); return TaskState(record)


def run_now(name, force=False):
    if ctx.in_query:
        raise TaskError("tasks.run_now() requires update context")
    result = _execute(_validate_name(name), force=force); _schedule(); return result


def status(name):
    return TaskState(_load(name))


def list():
    records = []
    for key in list_prefix("tasks", SCHEMA):
        record = kv.get(key)
        if record is not None:
            if record.get("schema") != SCHEMA:
                raise TaskError("unsupported task schema %r" % record.get("schema"))
            records.append(TaskState(record))
    return sorted(records, key=lambda record: record["name"])


def rename(old, new):
    _aliases[_validate_name(old)] = _validate_name(new)


def purge(name):
    record = _load(name)
    if record["state"] != "orphaned":
        raise TaskError("only orphaned tasks may be purged")
    return kv.delete(_key(name))


def restore():
    now = platform.now_ns()
    for key in list_prefix("tasks", SCHEMA):
        record = kv.get(key)
        name = record.get("name")
        if name in _aliases and _aliases[name] in _definitions:
            new = _aliases[name]
            record["name"] = new
            kv.delete(key)
            _save(record)
            name = new
        if name not in _definitions:
            record["state"] = "orphaned"; record["enabled"] = False; _save(record); continue
        if record["state"] == "running":
            record["state"] = "scheduled"
            record["active_runs"] = 0
        if record["enabled"] and record["next_run_at_ns"] < now:
            if record["catch_up"] == "skip":
                interval = record.get("interval_ns")
                if interval:
                    record["next_run_at_ns"] = now + interval
                else:
                    record["state"] = "completed"; record["enabled"] = False
            else:
                record["next_run_at_ns"] = now
        _save(record)
    # Definitions first introduced by this code version have no durable record
    # yet (and canister decorators intentionally do not write before KV bind).
    for name in sorted(_definitions):
        if kv.get(_key(name)) is None:
            _save(_record(_definitions[name], now))
    _schedule()
    log.info("tasks.restored", definitions=len(_definitions))


def _reset_for_tests():
    global _timer_handle, _supervisor_running
    _definitions.clear(); _aliases.clear(); _timer_handle = None; _supervisor_running = False


# Registration is intentionally lightweight and does not import Kybra.
from pyre import _lifecycle
try:
    _lifecycle.register("tasks.restore", restore, order=100)
except _lifecycle.LifecycleError:
    pass
