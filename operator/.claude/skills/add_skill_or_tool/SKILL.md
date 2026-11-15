---
name: add_skill_or_tool
description: When he asks to add a skill or a tool: check whether one already exists before anything is built.
---
<!-- pflab-operator s87.2 -->
1. List `.claude/skills/` and the tool names you have. Read their descriptions.
2. If one already does it, say which and show how to use it. Stop.
3. If not, write the proposal in `notes/proposal_<name>.md` (what, why not covered, how it is checked) and call `request_build` with it. He decides with a Yes.
