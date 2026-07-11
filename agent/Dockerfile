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

RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /agent
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py ./

ENTRYPOINT ["python", "agent.py"]
