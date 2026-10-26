# The workshop's sandbox (S64 Phase 4): model-written calculations run here, with no network, a read-only root,
# 2 GB of memory, 2 CPUs and no new privileges (src/pflab/agents/sandbox.py). The libraries are pinned to the exact versions
# of the main .venv, so a calculation gives the same numbers inside and outside.
#
# Build, from D:\portfolio_lab (the context is the repo root; .dockerignore lets only the runner in):
#     docker build -t pflab-sandbox:1 -f sandbox/Dockerfile .
FROM python:3.13-slim

RUN pip install --no-cache-dir numpy==2.5.3 pandas==3.0.5 pyarrow==25.0.1 scipy==1.18.1 statsmodels==0.14.6 \
    && useradd --create-home --uid 1000 runner

COPY src/pflab/agents/workshop_runner.py /app/runner.py

USER runner
WORKDIR /work
