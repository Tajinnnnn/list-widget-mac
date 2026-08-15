import json
import subprocess

import state
from config import APP_TITLE, CHECK_INTERVAL_SECONDS
from periodic import run_periodic


def applescript_quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title, message):
    script = f"display notification {applescript_quote(message)} with title {applescript_quote(title)}"
    try:
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception:
        pass


def _check_due_tasks_tick():
    try:
        result = state.window.evaluate_js("window.__checkDueTasks()")
        due_items = json.loads(result) if result else []
    except Exception:
        due_items = []
    for item in due_items:
        notify(f"Due now — {item.get('list', APP_TITLE)}", item.get("text", ""))


def notification_loop():
    run_periodic(CHECK_INTERVAL_SECONDS, _check_due_tasks_tick)
