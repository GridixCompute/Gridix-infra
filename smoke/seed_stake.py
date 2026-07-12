"""Bootstrap a provider's stake so the production matcher will assign it work.

The production scheduler installs ``ReputationMatcher``, which refuses any provider below
``min_provider_stake`` (default 100). There is no HTTP endpoint to fund stake, so this
script credits it directly through the double-entry ledger (``deposit_stake``). It is meant
to run INSIDE the api container, which already has the app and its full environment:

    docker compose exec -T \
        -e SEED_PROVIDER_ID=<provider-uuid> -e SEED_AMOUNT=200 \
        api python < smoke/seed_stake.py

``drive_smoke.py`` invokes this for you; run it by hand only if you drive P0 manually.
"""

import asyncio
import os
import uuid
from decimal import Decimal

from app.db import get_sessionmaker
from app.ledger import deposit_stake, provider_stake


async def main() -> None:
    provider_id = uuid.UUID(os.environ["SEED_PROVIDER_ID"])
    amount = Decimal(os.environ.get("SEED_AMOUNT", "200"))
    async with get_sessionmaker()() as session:
        await deposit_stake(session, provider_id, amount)
        await session.commit()
        total = await provider_stake(session, provider_id)
    print(f"provider {provider_id} stake is now {total}")


if __name__ == "__main__":
    asyncio.run(main())
