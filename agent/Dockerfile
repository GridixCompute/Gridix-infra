# GRIDIX provider agent. The agent shells out to the host Docker daemon to run job
# containers, so it needs the docker CLI and access to /var/run/docker.sock at runtime:
#
#   docker run --rm \
#     -e GRIDIX_API_URL=https://coordinator.example.com \
#     -e GRIDIX_PROVIDER_KEY=grdx_... \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     gridix-agent
#
# Mounting the docker socket grants host-level control; run the agent only on machines
# the provider owns, and keep job containers hardened (that is build_run_argv's job).
FROM python:3.11-slim

# docker.io's CLI client (/usr/bin/docker) is a *recommended* package, so it is dropped by
# --no-install-recommends — and the agent shells out to `docker`. Install with recommends so
# the client is present (the agent uses the host daemon via the mounted socket, not dockerd).
RUN apt-get update \
    && apt-get install -y docker.io \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /agent
COPY requirements.txt ./
# Install deps, then upgrade bundled build tooling past its fixable CVEs (Trivy gate).
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --upgrade pip setuptools "wheel>=0.46.2" "jaraco.context>=6.1.0"
COPY agent.py ./

ENTRYPOINT ["python", "agent.py"]
