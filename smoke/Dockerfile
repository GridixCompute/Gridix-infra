# Minimal smoke-test image. One Dockerfile builds three variants via --build-arg SCRIPT:
#   docker build -f smoke/Dockerfile --build-arg SCRIPT=run.py      -t gridix-smoke .
#   docker build -f smoke/Dockerfile --build-arg SCRIPT=netprobe.py -t gridix-smoke-netprobe .
#   docker build -f smoke/Dockerfile --build-arg SCRIPT=sleeper.py  -t gridix-smoke-sleeper .
#
# The agent runs every container with `--user 65534:65534 --read-only` regardless of any
# USER line here, so the chosen script must not need root or a writable rootfs (only the
# bind-mounted output dir and the /tmp tmpfs are writable).
FROM python:3.11-slim

ARG SCRIPT=run.py
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GRIDIX_SCRIPT=${SCRIPT}

COPY smoke/scripts/ /scripts/

# exec so the workload is PID 1 and receives the agent's kill signal promptly on timeout.
ENTRYPOINT ["sh", "-c", "exec python /scripts/${GRIDIX_SCRIPT}"]
