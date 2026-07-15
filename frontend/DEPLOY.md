# Deploying the GRIDIX frontend (Sesi 14.3)

The app is a Next 15 App Router site. It talks to the coordinator only through
same-origin route handlers (`/api/*`), so the browser never holds an API key.
Two supported paths: Vercel (managed, preview deploys per PR) or self-host Docker
(consistent with the backend on a VPS).

## Environment

`NEXT_PUBLIC_*` values are validated at boot (`src/lib/config/env.ts`) and inlined
into the client bundle **at build time** — set them before/at build, not just at
runtime.

| Variable                      | Example                                        |
| ----------------------------- | ---------------------------------------------- |
| `NEXT_PUBLIC_API_URL`         | `https://api.gridix.example` (the coordinator) |
| `NEXT_PUBLIC_RPC_URL`         | `https://ethereum-sepolia-rpc.publicnode.com`  |
| `NEXT_PUBLIC_CHAIN_ID`        | `11155111` (Sepolia)                           |
| `NEXT_PUBLIC_ESCROW_ADDRESS`  | `0x…`                                          |
| `NEXT_PUBLIC_STAKING_ADDRESS` | `0x…`                                          |
| `NEXT_PUBLIC_USDC_ADDRESS`    | `0x…`                                          |

Optional: `NEXT_PUBLIC_SENTRY_DSN` (see error tracking) — the observability sink
is a no-op until you initialise it.

## Option A — Vercel (preview deploys per PR)

1. Import the repo; set the project root to `frontend/`.
2. Add the env vars above (Production + Preview scopes).
3. Every PR gets an automatic **preview URL**; `main` deploys to production.
4. Add your domain in the Vercel dashboard — TLS is provisioned automatically.

Vercel builds and runs Next natively; the `output: "standalone"` setting is
ignored there.

## Option B — Self-host with Docker

The repo ships a multi-stage `Dockerfile` that emits Next's standalone server and
runs it as a non-root user.

```bash
docker build \
  --build-arg NEXT_PUBLIC_API_URL=https://api.gridix.example \
  --build-arg NEXT_PUBLIC_RPC_URL=https://ethereum-sepolia-rpc.publicnode.com \
  --build-arg NEXT_PUBLIC_CHAIN_ID=11155111 \
  --build-arg NEXT_PUBLIC_ESCROW_ADDRESS=0x... \
  --build-arg NEXT_PUBLIC_STAKING_ADDRESS=0x... \
  --build-arg NEXT_PUBLIC_USDC_ADDRESS=0x... \
  -t gridix-web ./frontend

docker run -d --name gridix-web -p 3000:3000 --restart=always gridix-web
```

Put it behind a TLS-terminating reverse proxy (Caddy/nginx/Traefik) mapped to your
domain — e.g. Caddy gives automatic Let's Encrypt certificates:

```
gridix.example {
  reverse_proxy localhost:3000
}
```

## Definition of Done

- A public HTTPS URL (not localhost) serves the app.
- The domain resolves, TLS is valid, and the security headers (see `SECURITY.md`)
  are present on responses.
- The frontend reaches the coordinator at `NEXT_PUBLIC_API_URL`.

> The final DNS/TLS/hosting step needs an account and a domain, so it's done by
> the operator — everything the deploy needs (standalone build, Dockerfile, env
> contract, reverse-proxy config) is here.
