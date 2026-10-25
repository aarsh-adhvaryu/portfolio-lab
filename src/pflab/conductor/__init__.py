"""The conductor (S53): one loop over the agents, run by the service every 15 minutes.

Each pass it works out the market's mode (`calendar`), checks that the market data, the ledger and the service are
in step and lists what is behind (`sync`), asks the investor for what only he can provide (a file, a login, a decision) and
drops the asks that resolved themselves, writes the fact sheet the local model reads (`situation`), and sends the
notes a person would: "back after N days, catching up", "markets shut until Monday: switch me on Sunday evening".
The flow is plain code: when to do what never depends on a model. Models sit only where text needs judgement.
"""
