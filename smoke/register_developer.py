"""Sign a smoke developer in through the real wallet flow and print its identity + key.

The unauthenticated ``POST /developers`` factory is gone: a developer only comes to exist
through SIWE sign-in (``/auth/verify`` find-or-creates the account), and API keys are
post-login credentials minted from ``/developers/me/keys``. Smoke drivers therefore sign
in the way a real developer does — SIWE with a throwaway wallet — then mint a long-lived
programmatic key, which is the credential the old route used to hand out. Runs INSIDE the
api container (same pattern as ``seed_stake.py`` / ``onboard_provider.py``), driving the
app in-process so it needs no network reachability assumptions:

    docker compose exec -T -e SMOKE_DEVELOPER_LABEL=smoke-dev \
        api python < smoke/register_developer.py

Prints one JSON object: ``{"id": <developer-id>, "api_key": <programmatic key>}``. The key
is shown once; hand it to the driver as the developer's bearer token.
"""

import asyncio
import json
import os

from app.main import create_app
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient


async def main() -> None:
    label = os.environ.get("SMOKE_DEVELOPER_LABEL", "smoke-dev")
    account = Account.create()  # throwaway developer wallet for this smoke run
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
        body = verified.json()
        session_key = body["api_key"]

        minted = await client.post(
            "/developers/me/keys",
            headers={"Authorization": f"Bearer {session_key}"},
            json={"label": label},
        )
        assert minted.status_code == 201, minted.text
    print(json.dumps({"id": body["developer_id"], "api_key": minted.json()["api_key"]}))


asyncio.run(main())
