"""The knowledge graph, rebuilt on the agreed design (S81 B7, KG_AUDIT_S80.md).

Three layers and a position layer; nothing is in the graph without an ISIN, a source and a date.

  scope     the names the news collection and the graph cover (`data/kg/scope.json`)
  news      the one-year article collection (GDELT GKG daily files, article text by trafilatura)
  build     facts (by ISIN, structured sources), relations (named rules), events (confident rules)
  position  each holding's lots, cost, days to 12 months, gain, exemption used, exit plan, storylines
  audit     the nightly audit as code
  study     the "graph earns its place" measurement (protocol `docs/protocols/s81_kg_study_protocol.md`)

The graph's switch is `configs/kg2.toml` `[kg] on` (default OFF); it is turned ON only when the audit passes.
"""
