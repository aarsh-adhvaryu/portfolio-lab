# S61 the model slider: results

Scored 2026-10-25 14:14 by the registered rules (`docs/llm/s61_slider_protocol.md`); defaults written to `configs/models.toml`.

| job | default | basis |
|---|---|---|
| answers | local | checked of 38: {'local': 22, 'haiku': 12, 'sonnet': 3, 'cascade': 23}; best 23, margin 2 |
| materiality | haiku | accuracy haiku 0.865, sonnet 0.870; monthly at live volume haiku Rs 0, sonnet Rs 4 (readers' share Rs 150); bar 90% |
| research | sonnet | Sonnet share 0.55 (needs 0.45); kept {'claude-opus-5-5': 0.934, 'claude-sonnet-5-5': 0.894} |
| workshop | sonnet | Sonnet 10/10, wrong but checked 0 |

| web | opus | not scored: the part stopped twice at its budget (protocol amendment 2); Opus stays |

## Reading (2026-10-25)
- **Live answers:** the local model checks 22 of 38, local-then-Haiku 23, Haiku 12, Sonnet 3; 9 questions never reached
  Haiku or Sonnet (their facts carry FD numbers, kept on this PC by the egress list). Local is within 2 of the best and
  cheapest, so it stays: live answers keep the GPU for now. Sonnet's drafts mostly failed the guard (claims without the
  `[F:name]` citation it requires).
- **Materiality:** Haiku 86.5%, Sonnet 87.0% at effort low: neither reaches 90%; Haiku stays, and the gatekeeper and the
  brain judge what matters again downstream.
- **Research notes:** Sonnet won or tied 55% of the 20 (needs 45%), kept 89% of its words against Opus's 93%, at half
  the cost (Rs 60 against Rs 117 for the 20). Sonnet is the default; Opus stays one click away in Settings.
- **Workshop:** both models 10 of 10 correct on the current prompt, none wrong but marked checked (Opus Rs 45, Sonnet
  Rs 25). Sonnet writes; the independent second writing is now always the other model (Opus), so a model never checks
  itself. Amendment 1's check passed (Opus still passes on the current prompt): the parameter instruction stays.
- **Spend:** about Rs 900 for S61 in all, Rs 600 of it on the two stopped web attempts (Claude Code's budget error).
