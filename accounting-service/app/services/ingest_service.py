import logging
import time
from typing import List, Tuple

from pydantic import ValidationError

from .. import config
from ..errors import BatchTooLarge, UnsupportedSchemaVersion
from ..models.events import EventBatch, IngestResult, RejectedEvent, UsageEvent
from ..repositories.ledger_repository import LedgerRepository
from .rollup_service import RollupService

log = logging.getLogger(__name__)


def to_ledger_doc(event: UsageEvent, schema_version: int, ingested_at: int) -> dict:
    doc = event.model_dump(mode="json")
    doc["_id"] = doc.pop("callId")
    doc["schemaVersion"] = schema_version
    doc["ingestedAt"] = ingested_at
    return doc


class IngestService:
    def __init__(self, ledger: LedgerRepository, rollups: RollupService):
        self._ledger, self._rollups = ledger, rollups
        self.rejected_total = 0  # since process start; surfaced by /internal/stats

    async def ingest(self, batch: EventBatch) -> Tuple[IngestResult, List[dict]]:
        """Returns the result plus the docs actually inserted (Phase 2 rollups use these)."""
        if batch.schemaVersion not in config.SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaVersion(f"schemaVersion {batch.schemaVersion} is not supported")
        if len(batch.events) > config.MAX_BATCH_SIZE:
            raise BatchTooLarge(f"batch exceeds {config.MAX_BATCH_SIZE} events")

        now = int(time.time() * 1000)
        valid, rejected, seen = [], [], set()
        for raw in batch.events:
            call_id = raw.get("callId") if isinstance(raw, dict) else None
            try:
                event = UsageEvent.model_validate(raw)
            except ValidationError as exc:
                rejected.append(RejectedEvent(callId=call_id, reason=_reason(exc)))
                continue
            if event.callId in seen:
                continue  # duplicate within the batch: counted below as a duplicate
            seen.add(event.callId)
            valid.append(to_ledger_doc(event, batch.schemaVersion, now))

        inserted_ids = set(await self._ledger.insert_many(valid))
        inserted = [d for d in valid if d["_id"] in inserted_ids]
        try:
            await self._rollups.apply(inserted)
        except Exception:  # ledger is the source of truth; `rollups verify/rebuild` repairs drift
            log.exception("rollup update failed for %d ledger rows", len(inserted))
        self.rejected_total += len(rejected)
        for r in rejected:
            log.warning("usage event rejected", extra={"callId": r.callId, "reason": r.reason})
        duplicates = len(batch.events) - len(rejected) - len(inserted)
        return IngestResult(accepted=len(inserted), duplicates=duplicates, rejected=rejected), inserted


def _reason(exc: ValidationError) -> str:
    first = exc.errors()[0]
    return f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
