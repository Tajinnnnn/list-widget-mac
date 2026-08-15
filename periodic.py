import state


def run_periodic(interval_seconds, work_fn, run_immediately=False):
    state.window.events.loaded.wait(timeout=15)
    if run_immediately:
        work_fn()
    while not state.stop_event.is_set():
        if state.stop_event.wait(interval_seconds):
            break
        work_fn()
