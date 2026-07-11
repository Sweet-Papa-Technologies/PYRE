from pyre import _platform, kv
from pyre import tasks


def drive(result, replies=None):
    if not hasattr(result, "send"):
        return result
    replies = iter(replies or [])
    sent = None
    while True:
        try:
            result.send(sent)
            sent = next(replies, {"Ok": b"ok"})
        except StopIteration as done:
            return done.value


class FakePlatform:
    def __init__(self):
        self.now = 1_000
        self.timers = {}
        self.next_handle = 1

    def now_ns(self):
        return self.now

    def set_timer(self, delay_ns, callback):
        handle = self.next_handle; self.next_handle += 1
        self.timers[handle] = (self.now + delay_ns, callback)
        return handle

    def clear_timer(self, handle):
        self.timers.pop(handle, None)

    def advance(self, ns):
        self.now += ns
        while True:
            due = sorted((at, handle, callback) for handle, (at, callback) in self.timers.items() if at <= self.now)
            if not due:
                break
            _, handle, callback = due[0]
            self.timers.pop(handle)
            drive(callback())


def setup_function():
    kv._backend = kv._DevBackend()
    kv.ctx.in_query = False
    tasks._reset_for_tests()
    _platform.install_adapter(FakePlatform())


def teardown_function():
    _platform.reset_adapter()


def test_interval_one_shot_controls_and_deterministic_listing():
    ran = []

    @tasks.every(seconds=2, name="z")
    def interval():
        ran.append("z")

    @tasks.after(seconds=1, name="a")
    def once():
        ran.append("a")

    assert [item["name"] for item in tasks.list()] == ["a", "z"]
    _platform._adapter.advance(1_000_000_000)
    assert ran == ["a"]
    assert tasks.status("a")["state"] == "completed"
    tasks.pause("z")
    _platform._adapter.advance(3_000_000_000)
    assert ran == ["a"]
    tasks.resume("z")
    _platform._adapter.advance(0)
    assert ran == ["a", "z"]
    tasks.cancel("z")
    assert tasks.status("z")["state"] == "cancelled"


def test_failure_is_sanitized_and_run_now_rejects_query():
    @tasks.after(seconds=5, name="bad")
    def bad():
        raise ValueError("secret-ish\nline")

    assert tasks.run_now("bad") is False
    state = tasks.status("bad")
    assert state["failure_count"] == 1
    assert "\n" not in state["last_error"]
    kv.ctx.in_query = True
    try:
        try:
            tasks.run_now("bad")
        except tasks.TaskError as exc:
            assert "update context" in str(exc)
        else:
            raise AssertionError("query run_now unexpectedly succeeded")
    finally:
        kv.ctx.in_query = False


def test_restore_skip_catchup_and_orphan():
    @tasks.every(seconds=2, name="live", catch_up="skip")
    def live():
        pass

    orphan = dict(tasks.status("live"))
    orphan["name"] = "removed"
    kv.set(tasks._key("removed"), orphan)
    _platform._adapter.now += 10_000_000_000
    tasks.restore()
    assert tasks.status("live")["next_run_at_ns"] == _platform._adapter.now + 2_000_000_000
    assert kv.get(tasks._key("removed"))["state"] == "orphaned"
    assert [item["name"] for item in tasks.list()] == ["live", "removed"]


def test_bounded_due_batch():
    calls = []
    for index in range(tasks.MAX_DUE_PER_WAKE + 3):
        tasks.after(seconds=1, name="job-%02d" % index)(lambda i=index: calls.append(i))
    _platform._adapter.now += 1_000_000_000
    assert drive(tasks._supervisor()) == tasks.MAX_DUE_PER_WAKE
    assert len(calls) == tasks.MAX_DUE_PER_WAKE


def test_async_callback_runs_through_pump_and_finishes_after_reply():
    events = []

    class Future:
        def __await__(self):
            result = yield self
            return result
        __iter__ = __await__
        def _to_kybra_call(self): return "raw-call"
        def _process_call_result(self, result): return result["Ok"]

    @tasks.after(seconds=1, name="async")
    async def async_task():
        value = await Future()
        events.append(value)

    _platform._adapter.now += 1_000_000_000
    runner = tasks._supervisor()
    assert runner.send(None) == "raw-call"
    try:
        runner.send({"Ok": b"done"})
    except StopIteration as done:
        assert done.value == 1
    assert events == [b"done"]
    assert tasks.status("async")["state"] == "completed"


def test_queue_one_drains_once_after_suspended_run():
    calls = []

    class Future:
        def __await__(self):
            yield self
        __iter__ = __await__
        def _to_kybra_call(self): return "wait"
        def _process_call_result(self, result): return result

    @tasks.every(seconds=1, name="queued", overlap="queue_one")
    async def queued():
        calls.append("start")
        await Future()

    first = tasks.run_now("queued")
    assert first.send(None) == "wait"
    assert tasks.run_now("queued") is False
    assert tasks.status("queued")["queued"] is True
    try: first.send({"Ok": b"ok"})
    except StopIteration: pass
    assert tasks.status("queued")["next_run_at_ns"] == _platform._adapter.now


def test_allow_tracks_multiple_active_runs_and_pause_survives_completion():
    pending = []
    class Future:
        def __await__(self): yield self
        __iter__ = __await__
        def _to_kybra_call(self): return "wait"
        def _process_call_result(self, result): return result

    @tasks.every(seconds=1, name="parallel", overlap="allow")
    async def parallel():
        pending.append(True); await Future()

    first, second = tasks.run_now("parallel"), tasks.run_now("parallel")
    assert first.send(None) == "wait" and second.send(None) == "wait"
    assert tasks.status("parallel")["active_runs"] == 2
    tasks.pause("parallel")
    for runner in (first, second):
        try: runner.send({"Ok": b"done"})
        except StopIteration: pass
    state = tasks.status("parallel")
    assert state["active_runs"] == 0 and state["state"] == "paused"


def test_canister_registration_defers_stable_writes_and_timers_until_restore(monkeypatch):
    monkeypatch.setattr(tasks, "in_canister", lambda: True)
    before = list(kv.keys())
    @tasks.after(seconds=2, name="deferred")
    def deferred(): pass
    assert kv.keys() == before and _platform._adapter.timers == {}
    tasks.restore()
    assert tasks.status("deferred")["state"] == "scheduled"
    assert _platform._adapter.timers
