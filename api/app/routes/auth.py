"""Wallet sign-in: issue a SIWE challenge, verify the signature, mint a session.

The wallet is the identity. A first sign-in creates the developer; later ones resolve to
it. No API key is ever shown to a person — the session credential is minted here and goes
straight into the caller's httpOnly cookie.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from loguru import logger
from sqlalchemy import select, update

from app.deps import SessionDep, SettingsDep
from app.models import ApiKey, AuthNonce, Developer, OwnerType
from app.schemas import NonceResponse, SessionResponse, VerifyRequest
from app.security import generate_api_key, hash_api_key, key_prefix
from app.siwe import (
    as_utc,
    build_message,
    challenge_expiry,
    generate_nonce,
    normalize_address,
    recover_signer,
    utcnow,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for every rejection. Which check failed — unknown nonce, spent nonce,
# expired nonce, wrong signer — is not the caller's business, and saying so would hand an
# attacker a probe for enumerating live challenges.
_REJECTED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature verification failed."
)


@router.get("/nonce", response_model=NonceResponse)
async def issue_nonce(
    session: SessionDep,
    settings: SettingsDep,
    address: str = Query(max_length=42, description="The wallet address that will sign."),
) -> NonceResponse:
    """Compose and store a single-use SIWE challenge for ``address``.

    The full EIP-4361 message is built here, from server settings, and persisted. The
    wallet signs it verbatim; /auth/verify checks against the stored copy. That is why
    ``domain`` and ``chainId`` cannot be forged: the client never states them.
    """
    normalized = normalize_address(address)
    if normalized is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Not a wallet address."
        )

    now = utcnow()
    expires_at = challenge_expiry(now, settings.siwe_nonce_ttl_seconds)
    nonce = generate_nonce()
    message = build_message(
        domain=settings.siwe_domain,
        uri=settings.siwe_uri,
        address=normalized,
        chain_id=settings.chain_id,
        nonce=nonce,
        issued_at=now,
        expires_at=expires_at,
    )
    session.add(
        AuthNonce(
            nonce=nonce,
            address=normalized,
            message=message,
            expires_at=expires_at,
        )
    )
    await session.flush()
    return NonceResponse(nonce=nonce, message=message, expires_at=expires_at)


@router.post("/verify", response_model=SessionResponse)
async def verify_signature(
    body: VerifyRequest, session: SessionDep, settings: SettingsDep
) -> SessionResponse:
    """Verify a signed challenge and return a session credential.

    Order matters: the nonce is claimed (atomically, once) before the signature is
    checked, so a replay cannot ride on a slow verification.
    """
    address = normalize_address(body.address)
    if address is None:
        raise _REJECTED

    challenge = await session.scalar(select(AuthNonce).where(AuthNonce.nonce == body.nonce))
    if challenge is None:
        raise _REJECTED

    now = utcnow()
    if not await _claim_nonce(session, challenge, now):
        # Already spent, or expired. Either way this challenge buys nothing.
        raise _REJECTED

    # The challenge is bound to the address it was issued to; a signature that recovers to
    # anyone else — including a valid signature from a different wallet — is not this
    # challenge's answer.
    if challenge.address != address:
        raise _REJECTED

    signer = recover_signer(challenge.message, body.signature)
    if signer is None or signer != challenge.address:
        raise _REJECTED

    developer = await _find_or_create_developer(session, address)
    plaintext, expires_at = await _mint_session_key(session, developer, settings, now)
    logger.info("wallet sign-in for developer {} ({})", developer.id, address)
    return SessionResponse(
        developer_id=developer.id,
        name=developer.name,
        wallet_address=address,
        api_key=plaintext,
        expires_at=expires_at,
    )


async def _claim_nonce(session: SessionDep, challenge: AuthNonce, now: datetime) -> bool:
    """Spend the challenge. True only for the caller that wins the race.

    A conditional UPDATE (``used_at IS NULL``) is the whole replay defence: two requests
    presenting the same signature both reach here, exactly one matches a row, and the
    loser is rejected. Checking-then-writing in Python would let both through.
    """
    if as_utc(challenge.expires_at) <= now:
        return False
    result = await session.execute(
        update(AuthNonce)
        .where(AuthNonce.id == challenge.id, AuthNonce.used_at.is_(None))
        .values(used_at=now)
    )
    return result.rowcount == 1


async def _find_or_create_developer(session: SessionDep, address: str) -> Developer:
    """Resolve the developer owning ``address``, creating one on first sign-in.

    This is the registration flow: a new wallet becomes an account with no form to fill
    and no key to copy. The address is the identity, and the same address is the one
    GridixEscrow accepts deposits from — one identity, not two.
    """
    developer = await session.scalar(select(Developer).where(Developer.wallet_address == address))
    if developer is not None:
        return developer

    # Named from the address rather than user input: it cannot collide with the reserved
    # "__gridix_" prefix (H12), and the user renames it later if they care.
    developer = Developer(name=f"{address[:6]}…{address[-4:]}", wallet_address=address)
    session.add(developer)
    await session.flush()
    logger.info("auto-registered developer {} for wallet {}", developer.id, address)
    return developer


async def _mint_session_key(
    session: SessionDep, developer: Developer, settings: SettingsDep, now: datetime
) -> tuple[str, datetime]:
    """Create the browser session credential: an expiring, labelled ApiKey.

    Reusing ApiKey means every existing route authenticates a wallet session with no new
    code path — one mechanism to reason about, not two.
    """
    plaintext = generate_api_key()
    expires_at = challenge_expiry(now, settings.session_ttl_seconds)
    session.add(
        ApiKey(
            owner_type=OwnerType.developer,
            developer_id=developer.id,
            key_hash=hash_api_key(plaintext, settings.api_hmac_key),
            prefix=key_prefix(plaintext),
            label="session",
            expires_at=expires_at,
        )
    )
    await session.flush()
    return plaintext, expires_at
