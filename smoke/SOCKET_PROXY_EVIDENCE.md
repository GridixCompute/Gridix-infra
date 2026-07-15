# Docker socket-proxy verification — EVIDENCE (security wave 2.1)

Runtime proof that the agent's Docker access is restricted to a job-runner surface and
CANNOT reach the escape endpoints. Run on a real Docker host (there is no Docker in CI/the
build sandbox), like the P0 smoke tests.

## Result: ✅ PASS

- **Host:** `fugazi@fugazi` — Docker **29.6.1**
- **Date:** 2026-07-15 20:34 UTC
- **Command:** `./smoke/verify_socket_proxy.sh` (from `agent/docker-socket-proxy.yml`)
- **Exit:** `0`

Raw output is saved in [`socket_proxy_run.txt`](socket_proxy_run.txt):

```text
==> allowed: version handshake + container/image listing (the runner needs these)
    /version -> 200 (allowed)
    /containers/json -> 200 (allowed)
    /images/json -> 200 (allowed)
==> DENIED (403): exec start, networks, volumes, build, info, secrets
    POST /exec/x/start -> 403 (denied)
    POST /build -> 403 (denied)
    GET  /networks -> 403 (denied)
    GET  /volumes -> 403 (denied)
    GET  /info -> 403 (denied)
    GET  /secrets -> 403 (denied)
==> allowed: a job container runs through the proxy (the runner path)
    hello-world ran via the proxy
PASS: socket proxy denies the exec-start escape + networks/volumes/build/info; the runner path works.
```

## What this proves

From inside a container on the proxy's network:

- The **escape** is denied: `POST /exec/{id}/start` — the endpoint that actually **runs a
  command inside a container** — returns **403**. So even though the runner is allowed to
  create containers, an attacker cannot use the socket to execute a command in one.
- Other dangerous surfaces are denied (403): `networks`, `volumes`, `build`, `info`,
  `secrets`.
- The **runner still works**: the version handshake, container/image listing, and actually
  running a container (`hello-world`) through `DOCKER_HOST=tcp://docker-socket-proxy:2375`
  all succeed.

### Note on `POST /containers/{id}/exec`

The exec-**create** endpoint (`POST /containers/{id}/exec`) is reachable through the
`CONTAINERS` section (it reaches the daemon → `400` on an empty body), but a created exec is
**inert**: without the blocked `POST /exec/{id}/start`, no command ever runs. The escape is
closed at the step that matters.

## Conclusion

The Docker socket-proxy restriction is verified on a real host. External providers may run
the agent behind this proxy (`agent/docker-socket-proxy.yml`, `DOCKER_HOST` → proxy, no raw
socket mount). The raw-socket install remains a documented, accepted risk for self-hosting
on a machine you own.
