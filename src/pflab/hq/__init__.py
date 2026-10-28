"""S59 the agent HQ (PLAN A16, docs/BUILT.md): a team of agents with a brain over them.

    egress     what may leave the PC (identity and banking never), checked in code before every paid call
    governor   every paid call priced first against tokens, passes and rupees a day, the layer's month, the cap
    llm        the one road to the API for HQ agents: gate, price, govern, log, send
    roster     the agents: name, model, what they read and write, how each one runs (existing modules, by import)
    board      tasks between agents and the investor's orders; a chain longer than MAX_HOPS goes to the brain
    reception  plain words and slash commands -> the agent that takes them (fixed rules, no model)
    phone      Telegram: plain messages to the receptionist, /calc /sim /web ... straight to an agent
    watcher    the drop folder -> the inbox
    readers    Haiku reads every public document: materiality, figures with their place, a summary
    brain      Opus in shadow mode: events in, decisions and predictions out, a journal; Sonnet as its rival
    keeper     the memory keeper: predictions scored, decisions followed up, the journal's numbers checked

HQ runs inside the dashboard's process (its runtime) or as jobs of the scheduled tick: never a second writer.
"""
