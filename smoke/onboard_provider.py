"""Onboard a smoke provider through the real wallet flow and print its identity.

The wallet-less ``POST /providers`` factory is gone: a provider only exists as a
capability of a wallet address, and the sole creation path is ``POST /providers/onboard``
from a signed-in wallet session. Smoke drivers therefore onboard the way a real operator
does — SIWE sign-in with a throwaway wallet, then onboard — instead of curling a
registration route. Runs INSIDE the api container (same pattern as ``seed_stake.py``),
driving the app in-process so it needs no network reachability assumptions:

    docker compose exec -T -e SMOKE_PROVIDER_NAME=smoke-prov \
        api python < smoke/onboard_provider.py

Prints one JSON object: ``{"id": ..., "api_key": ..., "wallet": ...}``. The key is the
node agent key, returned exactly once — hand it to the agent as GRIDIX_PROVIDER_KEY.
"""

import asyncio
import json
import os

from app.main import create_app
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient


async def main() -> None:
    name = os.environ.get("SMOKE_PROVIDER_NAME", "smoke-prov")
    account = Account.create()  # throwaway operator wallet for this smoke run
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://smoke") as client:
        challenge = (await client.get("/auth/nonce", params={"address": account.address})).json()
        verified = await client.post(
            "/auth/verify",
            json={
                "address": account.address,
                "signature": account.sign_message(
                    encode_defunct(text=challenge["message"])
                ).signature.hex(),
                "nonce": challenge["nonce"],
            },
        )
        assert verified.status_code == 200, verified.text
        session_key = verified.json()["api_key"]

        onboarded = await client.post(
            "/providers/onboard",
            headers={"Authorization": f"Bearer {session_key}"},
            json={"name": name},
        )
        assert onboarded.status_code == 201, onboarded.text
        body = onboarded.json()
    print(
        json.dumps(
            {"id": body["id"], "api_key": body["api_key"], "wallet": account.address.lower()}
        )
    )


asyncio.run(main())
