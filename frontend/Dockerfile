# Production image for the GRIDIX frontend (Sesi 14.3).
# Multi-stage: install deps, build the Next standalone server, run it as non-root.
#
# NEXT_PUBLIC_* values are inlined at build time, so pass them as build args:
#   docker build \
#     --build-arg NEXT_PUBLIC_API_URL=https://api.gridix.example \
#     --build-arg NEXT_PUBLIC_RPC_URL=https://ethereum-sepolia-rpc.publicnode.com \
#     --build-arg NEXT_PUBLIC_CHAIN_ID=11155111 \
#     --build-arg NEXT_PUBLIC_ESCROW_ADDRESS=0x... \
#     --build-arg NEXT_PUBLIC_STAKING_ADDRESS=0x... \
#     --build-arg NEXT_PUBLIC_USDC_ADDRESS=0x... \
#     -t gridix-web .

FROM node:20-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:20-alpine AS build
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Public env is baked into the client bundle at build time.
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_RPC_URL
ARG NEXT_PUBLIC_CHAIN_ID
ARG NEXT_PUBLIC_ESCROW_ADDRESS
ARG NEXT_PUBLIC_STAKING_ADDRESS
ARG NEXT_PUBLIC_USDC_ADDRESS
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_RPC_URL=$NEXT_PUBLIC_RPC_URL \
    NEXT_PUBLIC_CHAIN_ID=$NEXT_PUBLIC_CHAIN_ID \
    NEXT_PUBLIC_ESCROW_ADDRESS=$NEXT_PUBLIC_ESCROW_ADDRESS \
    NEXT_PUBLIC_STAKING_ADDRESS=$NEXT_PUBLIC_STAKING_ADDRESS \
    NEXT_PUBLIC_USDC_ADDRESS=$NEXT_PUBLIC_USDC_ADDRESS \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
# Run as the built-in non-root user.
USER node
# Standalone output bundles a minimal node_modules + server.js.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
