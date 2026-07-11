"""GRIDIX provider agent — runs untrusted job images in a hardened sandbox.

The agent registers as a provider (out of band), then loops:
``poll → fetch input → run_container → collect output → submit result``, heartbeating
throughout so the coordinator knows it is alive. The container is locked down by default
(no network, dropped capabilities, read-only rootfs, non-root, resource + pid + wall
limits) because the image is assumed hostile — that posture is the whole point of the
isolation layer, not a nice-to-have.

Run: ``GRIDIX_API_URL=... GRIDIX_PROVIDER_KEY=... python agent.py``
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import random
import signal
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from loguru import logger

# Mount points inside the container (stable contract with job images).
CONTAINER_INPUT = "/gridix/input"
CONTAINER_OUTPUT_DIR = "/gridix/output"
CONTAINER_OUTPUT_FILE = f"{CONTAINER_OUTPUT_DIR}/result"

# Unprivileged uid:gid the container process runs as (nobody:nogroup).
_NONROOT = "65534:65534"


@dataclass(frozen=True)
class AgentConfig:
    """Agent runtime configuration, sourced from the environment."""

    api_url: str
    provider_key: str
    workdir: Path
    poll_interval: float
    poll_jitter: float
    poll_backoff_max: float
    heartbeat_interval: float
    enable_gpu: bool
    relay_url: str
    relay_ping_interval: float

    @classmethod
    def from_env(cls) -> AgentConfig:
        """Build config from ``GRIDIX_*`` environment variables."""
        api_url = os.environ.get("GRIDIX_API_URL", "http://localhost:8000").rstrip("/")
        key = os.environ.get("GRIDIX_PROVIDER_KEY", "")
        if not key:
            raise RuntimeError("GRIDIX_PROVIDER_KEY is required")
        return cls(
            api_url=api_url,
            provider_key=key,
            workdir=Path(os.environ.get("GRIDIX_AGENT_WORKDIR", "/tmp/gridix-agent")),
            poll_interval=float(os.environ.get("GRIDIX_POLL_INTERVAL", "1")),
            poll_jitter=float(os.environ.get("GRIDIX_POLL_JITTER", "0.3")),
            poll_backoff_max=float(os.environ.get("GRIDIX_POLL_BACKOFF_MAX", "30")),
            heartbeat_interval=float(os.environ.get("GRIDIX_HEARTBEAT_INTERVAL", "15")),
            enable_gpu=os.environ.get("GRIDIX_ENABLE_GPU", "false").lower() == "true",
            # Optional NAT-traversal tunnel. Empty → agent runs poll-only (batch).
            relay_url=os.environ.get("GRIDIX_RELAY_URL", ""),
            relay_ping_interval=float(os.environ.get("GRIDIX_RELAY_PING_INTERVAL", "20")),
        )


def build_run_argv(
    *,
    image_ref: str,
    container_name: str,
    input_path: Path | None,
    output_dir: Path,
    resource_spec: dict,
    allow_egress: bool,
    enable_gpu: bool,
    exposed_port: int | None = None,
) -> list[str]:
    """Assemble the hardened ``docker run`` argv for one job.

    Hardening applied unconditionally: no network (unless the job explicitly requests
    egress), all Linux capabilities dropped, no privilege escalation, read-only rootfs
    with a small writable tmpfs for scratch, a non-root user, and memory / cpu / pid
    limits derived from the resource spec. The output directory is the one writable
    bind mount; input is mounted read-only. The caller enforces the wall-clock timeout.

    Endpoint-style jobs (``exposed_port`` set) must be reachable, so they get a bridge
    network with the port published to loopback only — the agent proxies tunnel requests
    to it; the outside world still can't reach the container directly.
    """
    cpu = int(resource_spec.get("cpu_cores", 1))
    mem_mb = int(resource_spec.get("memory_mb", 512))
    is_endpoint = exposed_port is not None
    argv: list[str] = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "bridge" if (allow_egress or is_endpoint) else "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--user",
        _NONROOT,
        "--pids-limit",
        "512",
        "--memory",
        f"{mem_mb}m",
        "--memory-swap",
        f"{mem_mb}m",  # disallow swap escape past the memory cap
        "--cpus",
        str(cpu),
        "-e",
        f"GRIDIX_OUTPUT={CONTAINER_OUTPUT_FILE}",
        "-v",
        f"{output_dir}:{CONTAINER_OUTPUT_DIR}:rw",
    ]
    if input_path is not None:
        argv += [
            "-e",
            f"GRIDIX_INPUT={CONTAINER_INPUT}",
            "-v",
            f"{input_path}:{CONTAINER_INPUT}:ro",
        ]
    if is_endpoint:
        # Publish to loopback only; the agent reaches it, the public internet cannot.
        argv += ["-p", f"127.0.0.1:{exposed_port}:{exposed_port}"]
    if resource_spec.get("gpu") and enable_gpu:
        argv += ["--gpus", "all"]
    argv.append(image_ref)
    return argv


def sha256_hex(data: bytes) -> str:
    """Return the hex sha256 digest of ``data`` (the proof anchor)."""
    return hashlib.sha256(data).hexdigest()


@dataclass
class RunResult:
    """Outcome of running one container."""

    exit_code: int
    timed_out: bool
    output: bytes


async def run_container(
    argv: list[str], container_name: str, timeout_seconds: int
) -> tuple[int, bool]:
    """Run the container, enforcing a hard wall-clock timeout.

    Returns ``(exit_code, timed_out)``. On timeout the container is force-killed and
    removed so nothing outlives its budget.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        if proc.returncode != 0 and err:
            tail = err.decode(errors="replace")[:500]
            logger.warning("container {} stderr: {}", container_name, tail)
        return proc.returncode or 0, False
    except TimeoutError:
        logger.warning("container {} exceeded {}s — killing", container_name, timeout_seconds)
        await _force_remove(container_name)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return 124, True


async def _force_remove(container_name: str) -> None:
    """Best-effort ``docker rm -f`` of a container."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except Exception as exc:  # noqa: BLE001 - cleanup is best effort
        logger.warning("failed to remove container {}: {}", container_name, exc)


class RelayTunnel:
    """Persistent outbound WebSocket tunnel to the relay (Session 7.2).

    Opens ONE connection to the relay, authenticates with the provider key, and holds it
    open with periodic pings so a NAT'd provider stays reachable. Reconnects with
    exponential backoff. Inbound request framing is handled in Session 7.3.
    """

    def __init__(self, config: AgentConfig, stop: asyncio.Event) -> None:
        self._cfg = config
        self._stop = stop

    async def run(self) -> None:
        import json

        import websockets  # lazy: only needed when a relay is configured

        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self._cfg.relay_url) as ws:
                    await ws.send(json.dumps({"type": "auth", "key": self._cfg.provider_key}))
                    resp = json.loads(await ws.recv())
                    if resp.get("type") != "auth_ok":
                        raise RuntimeError(f"relay auth failed: {resp}")
                    logger.info("relay tunnel established ({})", resp.get("provider_id"))
                    backoff = 1.0
                    await self._serve(ws)
            except Exception as exc:  # noqa: BLE001 - reconnect on any tunnel failure
                if self._stop.is_set():
                    break
                logger.warning("relay tunnel down, reconnecting in {:.1f}s: {}", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._cfg.poll_backoff_max)

    async def _serve(self, ws) -> None:
        import json

        ping = asyncio.create_task(self._ping_loop(ws))
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "request":
                    reply = await self._handle_request(msg)
                    await ws.send(json.dumps(reply))
                # pong and unknown frames are ignored.
        finally:
            ping.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ping

    async def _handle_request(self, msg: dict) -> dict:
        """Handle an inbound coordinator request delivered over the tunnel."""
        payload = msg.get("payload") or {}
        if payload.get("kind") == "endpoint":
            return await self._proxy_endpoint(msg, payload)
        # Non-endpoint control request: echo (round-trip probe).
        return {
            "type": "response",
            "request_id": msg.get("request_id"),
            "status": 200,
            "payload": {"echo": payload, "job_id": msg.get("job_id")},
        }

    async def _proxy_endpoint(self, msg: dict, payload: dict) -> dict:
        """Proxy an endpoint request to the job's container port on loopback."""
        port = payload["port"]
        path = payload.get("path", "/")
        url = f"http://127.0.0.1:{port}{path}"
        if payload.get("query"):
            url = f"{url}?{payload['query']}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as proxy:
                resp = await proxy.request(
                    payload.get("method", "GET"),
                    url,
                    content=payload.get("body", "").encode(),
                )
            inner = {
                "body": resp.text,
                "content_type": resp.headers.get("content-type", "application/octet-stream"),
            }
            status_code = resp.status_code
        except Exception as exc:  # noqa: BLE001 - report proxy failure as 502 to the caller
            inner = {"body": f"proxy error: {exc}"}
            status_code = 502
        return {
            "type": "response",
            "request_id": msg.get("request_id"),
            "status": status_code,
            "payload": inner,
        }

    async def _ping_loop(self, ws) -> None:
        import json

        while not self._stop.is_set():
            await asyncio.sleep(self._cfg.relay_ping_interval)
            await ws.send(json.dumps({"type": "ping"}))


class Agent:
    """Polls the coordinator and executes assigned jobs in a sandbox."""

    def __init__(self, config: AgentConfig, stop: asyncio.Event | None = None) -> None:
        self._cfg = config
        self._stop = stop or asyncio.Event()
        self._client = httpx.AsyncClient(
            base_url=config.api_url,
            headers={"Authorization": f"Bearer {config.provider_key}"},
            timeout=30.0,
        )
        config.workdir.mkdir(parents=True, exist_ok=True)

    def request_stop(self) -> None:
        """Signal the loop to stop; the current job's lease will lapse and reassign."""
        self._stop.set()

    def _jittered(self, base: float) -> float:
        """Return ``base`` scaled by ±poll_jitter to avoid thundering-herd re-polls."""
        return base * (1 + random.uniform(-self._cfg.poll_jitter, self._cfg.poll_jitter))

    async def run(self) -> None:
        """Main poll loop until stopped.

        The server long-polls, so a successful empty poll is followed by a short jittered
        pause. Connection errors back off exponentially (capped) so a flapping coordinator
        or network does not hammer the endpoint.
        """
        logger.info("agent started against {}", self._cfg.api_url)
        backoff = self._cfg.poll_interval
        try:
            while not self._stop.is_set():
                try:
                    job = await self._poll()
                    backoff = self._cfg.poll_interval  # healthy connection; reset
                except Exception as exc:  # noqa: BLE001 - back off and retry on any error
                    logger.warning("poll failed, backing off {:.1f}s: {}", backoff, exc)
                    await asyncio.sleep(self._jittered(backoff))
                    backoff = min(backoff * 2, self._cfg.poll_backoff_max)
                    continue
                if job is None:
                    await asyncio.sleep(self._jittered(self._cfg.poll_interval))
                    continue
                await self._handle_job(job)
        finally:
            await self._client.aclose()
            logger.info("agent stopped")

    async def _poll(self) -> dict | None:
        resp = await self._client.post("/agent/poll")
        resp.raise_for_status()
        return resp.json().get("job")

    async def _handle_job(self, job: dict) -> None:
        job_id = job["id"]
        logger.info("running job {}", job_id)
        await self._client.post(f"/agent/jobs/{job_id}/status", json={"status": "running"})

        heartbeat = asyncio.create_task(self._heartbeat_loop(job_id))
        try:
            result = await self._execute(job)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

        result_ref: str | None = None
        proof = {
            "output_sha256": sha256_hex(result.output),
            "exit_code": result.exit_code,
            "output_bytes": len(result.output),
        }
        if result.exit_code == 0 and not result.timed_out and result.output:
            result_ref = await self._upload_result(result.output)

        await self._client.post(
            f"/agent/jobs/{job_id}/result",
            json={
                "result_ref": result_ref,
                "exit_code": result.exit_code,
                "proof": proof,
                "timed_out": result.timed_out,
            },
        )
        logger.info("submitted result for job {} (exit={})", job_id, result.exit_code)

    async def _execute(self, job: dict) -> RunResult:
        job_id = job["id"]
        job_dir = self._cfg.workdir / job_id
        out_dir = job_dir / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        input_path = await self._fetch_input(job_id, job_dir)
        argv = build_run_argv(
            image_ref=job["image_ref"],
            container_name=f"gridix-{job_id}",
            input_path=input_path,
            output_dir=out_dir,
            resource_spec=job.get("resource_spec") or {},
            allow_egress=job.get("allow_egress", False),
            enable_gpu=self._cfg.enable_gpu,
            exposed_port=job.get("exposed_port"),
        )
        started = time.monotonic()
        exit_code, timed_out = await run_container(
            argv, f"gridix-{job_id}", int(job.get("timeout_seconds", 300))
        )
        logger.info("job {} finished in {:.1f}s", job_id, time.monotonic() - started)

        output_file = out_dir / "result"
        output = output_file.read_bytes() if output_file.exists() else b""
        return RunResult(exit_code=exit_code, timed_out=timed_out, output=output)

    async def _fetch_input(self, job_id: str, job_dir: Path) -> Path | None:
        resp = await self._client.get(f"/agent/jobs/{job_id}/input")
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        path = job_dir / "input"
        path.write_bytes(resp.content)
        return path

    async def _upload_result(self, output: bytes) -> str:
        resp = await self._client.post(
            "/agent/blobs", files={"file": ("result", output, "application/octet-stream")}
        )
        resp.raise_for_status()
        return resp.json()["ref"]

    async def _heartbeat_loop(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self._cfg.heartbeat_interval)
            try:
                await self._client.post("/agent/heartbeat", json={"job_id": job_id})
            except Exception as exc:  # noqa: BLE001 - transient; keep the job alive
                logger.warning("heartbeat failed for {}: {}", job_id, exc)


async def main() -> None:
    """Entrypoint: build the agent (and relay tunnel, if configured) until a signal."""
    config = AgentConfig.from_env()
    stop = asyncio.Event()
    agent = Agent(config, stop)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    tasks = [agent.run()]
    if config.relay_url:
        tasks.append(RelayTunnel(config, stop).run())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
