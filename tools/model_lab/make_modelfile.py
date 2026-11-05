"""Write an Ollama Modelfile for a GGUF made in the lab (A41, S79). Development only.

    python tools/model_lab/make_modelfile.py --gguf outputs/.../pflab-qwen3-8b-lab-q8_0.gguf --tag pflab-qwen3-8b-lab
    ollama create pflab-qwen3-8b-lab -f outputs/Modelfile.pflab-qwen3-8b-lab

The template is Ollama's own qwen3 chat template (so thinking on/off and tool calls behave as for the base tag; a GGUF imported
without it answers in the wrong format). Sampling follows Qwen's model card: non-thinking 0.7 / top_p 0.8 / top_k 20 / min_p 0,
thinking 0.6 / 0.95 / 20 / 0. The app overrides temperature (0) and seed on every call, so these are only the defaults of the tag.
The app never imports torch: once `ollama create` has run, the tag is just another local model.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_common as lab  # noqa: E402

SAMPLING = {"nonthinking": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "repeat_penalty": 1.0},
            "thinking": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "repeat_penalty": 1.0}}
STOPS = ("<|im_start|>", "<|im_end|>")

TEMPLATE = r'''
{{- $lastUserIdx := -1 -}}
{{- range $idx, $msg := .Messages -}}
{{- if eq $msg.Role "user" }}{{ $lastUserIdx = $idx }}{{ end -}}
{{- end }}
{{- if or .System .Tools }}<|im_start|>system
{{ if .System }}
{{ .System }}
{{- end }}
{{- if .Tools }}

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{{- range .Tools }}
{"type": "function", "function": {{ .Function }}}
{{- end }}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{"name": <function-name>, "arguments": <args-json-object>}
</tool_call>
{{- end -}}
<|im_end|>
{{ end }}
{{- range $i, $_ := .Messages }}
{{- $last := eq (len (slice $.Messages $i)) 1 -}}
{{- if eq .Role "user" }}<|im_start|>user
{{ .Content }}
{{- if and $.IsThinkSet (eq $i $lastUserIdx) }}
   {{- if $.Think -}}
      {{- " "}}/think
   {{- else -}}
      {{- " "}}/no_think
   {{- end -}}
{{- end }}<|im_end|>
{{ else if eq .Role "assistant" }}<|im_start|>assistant
{{ if (and $.IsThinkSet (and .Thinking (or $last (gt $i $lastUserIdx)))) -}}
<think>{{ .Thinking }}</think>
{{ end -}}
{{ if .Content }}{{ .Content }}
{{- else if .ToolCalls }}<tool_call>
{{ range .ToolCalls }}{"name": "{{ .Function.Name }}", "arguments": {{ .Function.Arguments }}}
{{ end }}</tool_call>
{{- end }}{{ if not $last }}<|im_end|>
{{ end }}
{{- else if eq .Role "tool" }}<|im_start|>user
<tool_response>
{{ .Content }}
</tool_response><|im_end|>
{{ end }}
{{- if and (ne .Role "assistant") $last }}<|im_start|>assistant
{{ if and $.IsThinkSet (not $.Think) -}}
<think>

</think>

{{ end -}}
{{ end }}
{{- end }}'''


def modelfile(gguf: str, mode: str = "nonthinking", system: Optional[str] = None) -> str:
    """The Modelfile text. `gguf` is written as given (use an absolute path or one relative to the Modelfile)."""
    if mode not in SAMPLING:
        raise ValueError(f"mode must be one of {sorted(SAMPLING)}")
    lines: List[str] = [f"FROM {gguf}", "", f'TEMPLATE """{TEMPLATE}"""']
    if system:
        lines.append(f'SYSTEM """{system}"""')
    for k, v in SAMPLING[mode].items():
        lines.append(f"PARAMETER {k} {v}")
    for s in STOPS:
        lines.append(f"PARAMETER stop {s}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gguf", required=True, help="path to the GGUF (absolute, or relative to the Modelfile)")
    ap.add_argument("--tag", default="pflab-qwen3-8b-lab", help="the Ollama tag you will create")
    ap.add_argument("--mode", choices=sorted(SAMPLING), default="nonthinking")
    ap.add_argument("--system", default=None)
    ap.add_argument("--out", type=Path, default=None, help="default outputs/Modelfile.<tag>")
    a = ap.parse_args(argv)
    out = a.out or lab.OUTPUTS / f"Modelfile.{a.tag}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(modelfile(a.gguf, a.mode, a.system), encoding="utf-8")
    print(f"wrote {out}")
    print(f"next: ollama create {a.tag} -f \"{out}\"   then   python tools/model_lab/run_evals.py --tag {a.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
