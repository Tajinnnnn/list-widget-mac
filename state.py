import threading

# Shared runtime state, mutated in place by whichever module owns the
# corresponding lifecycle (window_controls for window/visible, tray for
# tray_icon). Kept as module attributes rather than passed-around objects so
# every module sees the same live values without needing its own wiring.
window = None
tray_icon = None
visible = False
stop_event = threading.Event()
