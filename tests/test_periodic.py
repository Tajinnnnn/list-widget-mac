import json
import threading
import time

import pytest

import notifications
import state
import sync_worker
from periodic import run_periodic


class _FakeLoadedEvent:
    def __init__(self):
        self.wait_calls = []

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        return True


class _FakeEvents:
    def __init__(self):
        self.loaded = _FakeLoadedEvent()


class _FakeWindow:
    def __init__(self):
        self.events = _FakeEvents()


@pytest.fixture
def fake_window(monkeypatch):
    window = _FakeWindow()
    monkeypatch.setattr(state, "window", window)
    return window


@pytest.fixture
def real_stop_event(monkeypatch):
    # A real threading.Event that the test controls directly, standing in
    # for state.stop_event — run_periodic is exercised for real (not
    # mocked), so this needs genuine wait()/set() semantics.
    event = threading.Event()
    monkeypatch.setattr(state, "stop_event", event)
    return event


def test_run_periodic_waits_for_loaded_before_any_tick(fake_window, real_stop_event):
    real_stop_event.set()
    work_calls = []

    run_periodic(0.01, lambda: work_calls.append(1))

    assert fake_window.events.loaded.wait_calls == [15]
    # stop_event was already set before the loop and run_immediately
    # defaults to False, so the work function must never fire.
    assert work_calls == []


def test_run_immediately_true_runs_work_once_before_wait_loop(fake_window, real_stop_event):
    real_stop_event.set()
    work_calls = []

    run_periodic(0.01, lambda: work_calls.append(1), run_immediately=True)

    assert work_calls == [1]


def test_run_immediately_false_default_does_not_run_before_loop(fake_window, real_stop_event):
    real_stop_event.set()
    work_calls = []

    run_periodic(0.01, lambda: work_calls.append(1))

    assert work_calls == []


def test_stop_event_exits_promptly_not_after_full_interval(fake_window, real_stop_event):
    # Uses a deliberately long interval (60s) so the assertion only passes
    # if stop_event.wait(interval) is what wakes the loop up — not the
    # interval elapsing naturally.
    work_calls = []

    def work():
        work_calls.append(1)

    thread = threading.Thread(
        target=run_periodic, args=(60, work), kwargs={"run_immediately": True}
    )
    start = time.monotonic()
    thread.start()
    time.sleep(0.05)
    real_stop_event.set()
    thread.join(timeout=3)
    elapsed = time.monotonic() - start

    assert not thread.is_alive(), "run_periodic did not exit promptly when stop_event was set"
    assert elapsed < 3
    # Only the immediate run happened; the loop never got a chance to tick
    # again before stop_event short-circuited the wait.
    assert work_calls == [1]


def test_notification_loop_delegates_to_run_periodic_without_run_immediately(monkeypatch):
    # notification_loop had no "run once immediately" behavior before the
    # refactor (only the while loop) — confirm that's preserved by
    # checking it doesn't pass run_immediately=True.
    calls = []
    monkeypatch.setattr(notifications, "run_periodic", lambda *a, **k: calls.append((a, k)))

    notifications.notification_loop()

    assert calls == [
        ((notifications.CHECK_INTERVAL_SECONDS, notifications._check_due_tasks_tick), {})
    ]


def test_vault_sync_loop_delegates_to_run_periodic_with_run_immediately_true(monkeypatch):
    # vault_sync_loop called _run_vault_sync_cycle() once right after the
    # loaded.wait, before the while loop — confirm that's preserved as
    # run_immediately=True.
    calls = []
    monkeypatch.setattr(sync_worker, "run_periodic", lambda *a, **k: calls.append((a, k)))

    sync_worker.vault_sync_loop()

    assert calls == [
        (
            (sync_worker.VAULT_SYNC_INTERVAL_SECONDS, sync_worker._run_vault_sync_cycle),
            {"run_immediately": True},
        )
    ]


def test_check_due_tasks_tick_notifies_for_each_due_item(monkeypatch):
    class _EvalWindow:
        def evaluate_js(self, *_args, **_kwargs):
            return json.dumps(
                [
                    {"list": "Groceries", "text": "Buy milk"},
                    {"text": "No list key"},
                ]
            )

    monkeypatch.setattr(state, "window", _EvalWindow())
    notify_calls = []
    monkeypatch.setattr(
        notifications, "notify", lambda title, message: notify_calls.append((title, message))
    )

    notifications._check_due_tasks_tick()

    assert notify_calls == [
        ("Due now — Groceries", "Buy milk"),
        (f"Due now — {notifications.APP_TITLE}", "No list key"),
    ]


def test_check_due_tasks_tick_swallows_evaluate_js_errors(monkeypatch):
    class _BoomWindow:
        def evaluate_js(self, *_args, **_kwargs):
            raise Exception("boom")

    monkeypatch.setattr(state, "window", _BoomWindow())
    notify_calls = []
    monkeypatch.setattr(notifications, "notify", lambda *a, **k: notify_calls.append((a, k)))

    notifications._check_due_tasks_tick()  # must not raise

    assert notify_calls == []
