"""Session 12.6 — tamper-evident audit log (hash chain) is retained and verifiable."""

from app.audit_log import append_audit, audit_count, verify_audit_chain


async def test_audit_chain_is_intact_and_retained(session) -> None:
    for i in range(4):
        await append_audit(session, "slash_confirmed", {"i": i, "provider": f"p{i}"})
    await session.flush()
    assert await audit_count(session) == 4  # retained
    assert await verify_audit_chain(session) is True


async def test_tampering_breaks_the_chain(session) -> None:
    e0 = await append_audit(session, "settle", {"amount": 10})
    await append_audit(session, "settle", {"amount": 20})
    await session.flush()
    assert await verify_audit_chain(session) is True

    # Alter a historical entry's data → the chain no longer verifies.
    e0.data = {"amount": 999}
    await session.flush()
    assert await verify_audit_chain(session) is False


async def test_deletion_breaks_the_chain(session) -> None:
    await append_audit(session, "a", {})
    e1 = await append_audit(session, "b", {})
    await append_audit(session, "c", {})
    await session.flush()
    await session.delete(e1)  # remove a middle record
    await session.flush()
    assert await verify_audit_chain(session) is False
