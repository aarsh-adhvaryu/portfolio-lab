"""Never idle (S79 item 5): an agenda the system owns (`mind_agenda`) and works through whenever nothing urgent is happening.

    kinds.py    what can be put on the agenda: a producer finds candidates, a worker does one; `kinds.register(kind, producer, worker)` adds more
    items.py    the table: add (deduplicated by kind + subject + day), start, finish, skip, the per-kind yield
    picker.py   the next item: expected value x the kind's yield multiplier / cost, within the clock's MODE and the money governor
    runner.py   `tick(rt, now)` (refill if needed, do one item), `work_one`, `refill`, `snapshot(con)` for the World screen and the `agenda` tool

An act is USEFUL only if it changed a belief, a forecast weight, a decision, or answered him (`items.EFFECTS`); kinds whose acts are rarely
useful lose priority (never below a floor, so they are still tried now and then).
"""
