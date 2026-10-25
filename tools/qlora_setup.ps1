# S47 pass 2 (docs/llm/qlora_s47_pass2_protocol.md): the training environment, kept apart from .venv.
#
#   cd D:\portfolio_lab
#   powershell -ExecutionPolicy Bypass -File tools\qlora_setup.ps1             # .venv-train + tokenizer (~3.5 GB, ~10 min)
#   powershell -ExecutionPolicy Bypass -File tools\qlora_setup.ps1 -Weights    # also the base weights (~16 GB)
#
# Pins (torch build for CUDA 13.0; the driver reports CUDA 13.4): recorded in CLAUDE.md. Weights and tokenizer go to
# PFLAB_DATA_DIR\models\Qwen3-8B (gitignored) with the downloaded revision in REVISION.
param([switch]$Weights)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$data = if ($env:PFLAB_DATA_DIR) { $env:PFLAB_DATA_DIR } else { "D:\portfolio_lab\data" }
$dest = Join-Path $data "models\Qwen3-8B"

if (-not (Test-Path ".venv-train\Scripts\python.exe")) {
    $base = (& .venv\Scripts\python -c "import sys; print(sys.base_prefix)").Trim()
    & "$base\python.exe" -m venv .venv-train
}
$py = ".venv-train\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install "torch==2.14.1" --index-url https://download.pytorch.org/whl/cu130
& $py -m pip install "transformers==5.20.1" "peft==0.21.2" "bitsandbytes==0.50.2" "accelerate==1.15.0"
if ($LASTEXITCODE -ne 0) { throw "pip failed" }

$patterns = if ($Weights) { "None" } else { "['tokenizer*', 'vocab*', 'merges*', '*.json']" }
$script = @"
from huggingface_hub import HfApi, snapshot_download
from pathlib import Path
rev = HfApi().model_info('Qwen/Qwen3-8B').sha
p = snapshot_download('Qwen/Qwen3-8B', revision=rev, local_dir=r'$dest', allow_patterns=$patterns)
Path(p, 'REVISION').write_text(rev)
print('Qwen/Qwen3-8B', rev, '->', p)
"@
$tmp = Join-Path $env:TEMP "qlora_fetch.py"
Set-Content -Path $tmp -Value $script -Encoding utf8
& $py $tmp
& $py -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
Write-Host "SETUP DONE: next  $py tools\qlora_train.py --smoke --base $dest"
