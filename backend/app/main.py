import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .database import boards_collection, close_client, ensure_indexes
from .accounting.client import HttpUsageClient
from .accounting.fallback import FallbackReplayer
from .accounting.outbox import OutboxRepository
from .accounting.query_client import AccountingUnavailable, HttpUsageQueryClient
from .accounting.reconcile.alert_store import AlertStore
from .accounting.reconcile.cli import build_completeness, build_counters
from .accounting.reconcile.scheduler import ReconcileScheduler
from .accounting.worker import OutboxWorker
from .execution.events import events
from .integrations_client import HttpIntegrationsClient
from .execution.glow import migrate_board_glow
from .execution.registry import registry
from .routers import agents, alerts, auth, board_shares, boards, chats, labels, settings, task_fields, tools, usage
from .seed import default_boards
from .task_state import (
    migrate_legacy_board_statuses,
    migrate_legacy_task_statuses,
    reconcile_interrupted_runs,
    reconcile_orphaned_task_runs,
)

app = FastAPI(title="Manifestation Board API")

outbox_worker = OutboxWorker(OutboxRepository(), HttpUsageClient(timeout=10))
reconcile_scheduler = ReconcileScheduler(build_completeness(), build_counters(), OutboxRepository(),
                                         HttpUsageQueryClient(), AlertStore())

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(boards.router)
app.include_router(board_shares.router)
app.include_router(task_fields.router)
app.include_router(chats.router)
app.include_router(labels.router)
app.include_router(settings.router)
app.include_router(tools.router)
app.include_router(usage.router)
app.include_router(alerts.router)


@app.exception_handler(AccountingUnavailable)
async def accounting_unavailable(_request, _exc):
    return JSONResponse(status_code=503, content={"error": {
        "code": "accounting_unavailable", "message": "Usage history is temporarily unavailable"}})


@app.on_event("startup")
async def on_startup():
    await ensure_indexes()
    count = await boards_collection.count_documents({})
    if count == 0:
        await boards_collection.insert_many(default_boards())
    await migrate_legacy_task_statuses()
    await migrate_legacy_board_statuses()
    await migrate_board_glow()
    # Recover boards a prior process left "running"/"queued" mid-task — see
    # reconcile_interrupted_runs for why nothing else ever revisits them.
    await reconcile_interrupted_runs()
    # Catch-all sweep for any task_runs doc (including sub-agent runs) that
    # reconcile_interrupted_runs' board/task walk doesn't reach directly.
    await reconcile_orphaned_task_runs()
    # Usage delivery never gates startup: replay anything saved to the fallback
    # file, then let the worker drain the outbox whenever the service is reachable.
    try:
        await FallbackReplayer(OutboxRepository()).replay()
    except Exception:
        logging.getLogger("uvicorn.error").exception("usage fallback replay failed")
    outbox_worker.start()
    reconcile_scheduler.start()
    # Connectivity check only — never blocks startup if the service is down.
    ok = await HttpIntegrationsClient().ping()
    logging.getLogger("uvicorn.error").info(
        "integrations-service ping: %s", "ok" if ok else "UNREACHABLE"
    )


@app.on_event("shutdown")
async def on_shutdown():
    # Give connected SSE clients an explicit signal before their connection
    # just drops, then cancel in-flight runner tasks so they get a chance to
    # unwind cleanly instead of being killed mid-request by process exit.
    # DB status is left for reconcile_interrupted_runs/reconcile_orphaned_task_runs
    # to reconcile on the next startup.
    for board_id in registry.board_ids():
        await events.publish(
            board_id,
            {"boardId": board_id, "status": "interrupted", "statusReason": "Server is restarting"},
        )
    await registry.cancel_all()
    await reconcile_scheduler.stop()
    await outbox_worker.stop()
    close_client()


@app.get("/api/health")
async def health():
    return {"status": "ok"}
