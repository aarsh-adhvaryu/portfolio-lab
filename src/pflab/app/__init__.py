"""S54: the dashboard and the one-process system behind it (PLAN A8, A9).

`launcher` starts everything from the desktop shortcut and stops it when the window closes; `runtime` owns the PM
store and runs the scheduler, the live-price poller and background caches; `views` builds each screen's data from the
system's own tested functions; `server` serves the screens and their data on 127.0.0.1 only.
"""
