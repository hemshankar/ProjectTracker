"""Readiness: database reachable and the ledger's indexes exist."""
from ..database import LEDGER_COLLECTION, ROLLUP_COLLECTION


async def check_ready(db) -> dict:
    try:
        await db.command("ping")
        ledger_idx = await db[LEDGER_COLLECTION].index_information()
        rollup_idx = await db[ROLLUP_COLLECTION].index_information()
    except Exception as exc:
        return {"ready": False, "reason": f"database unreachable: {type(exc).__name__}"}
    if len(ledger_idx) < 2 or len(rollup_idx) < 2:
        return {"ready": False, "reason": "indexes missing"}
    return {"ready": True}
