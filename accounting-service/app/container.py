"""Composition root: the only place concrete classes are named and wired."""
from dataclasses import dataclass
from typing import Any

from .database import get_database
from .repositories.mongo_ledger import MongoLedgerRepository
from .repositories.mongo_rollup import MongoRollupRepository
from .services.export_service import ExportService
from .services.ingest_service import IngestService
from .services.query_service import QueryService
from .services.rollup_service import RollupService
from .services.rows_service import RowsService
from .services.scheduler import RollupVerifyScheduler
from .services.stats_service import StatsService


@dataclass
class Container:
    db: Any
    ingest: IngestService
    rollups: RollupService
    query: QueryService
    rows: RowsService
    export: ExportService
    ledger: Any
    stats: StatsService
    verifier: RollupVerifyScheduler


def build_container(db) -> Container:
    ledger, rollup_repo = MongoLedgerRepository(db), MongoRollupRepository(db)
    rollups = RollupService(ledger, rollup_repo)
    ingest = IngestService(ledger, rollups)
    verifier = RollupVerifyScheduler(rollups)
    stats = StatsService(ledger, rollup_repo, lambda: ingest.rejected_total, lambda: verifier.last_result)
    return Container(db, ingest, rollups, QueryService(ledger, rollup_repo), RowsService(ledger),
                     ExportService(ledger), ledger, stats, verifier)


_container = None


def get_container() -> Container:
    global _container
    if _container is None:
        _container = build_container(get_database())
    return _container
