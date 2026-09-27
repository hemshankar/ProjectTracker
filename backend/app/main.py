from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .database import boards_collection, close_client, ensure_indexes
from .execution.events import events
from .execution.glow import migrate_board_glow
from .execution.registry import registry
from .routers import agents, auth, board_shares, boards, chats, labels, settings, tools
from .seed import default_boards
from .task_state import (
    migrate_legacy_board_statuses,
    migrate_legacy_task_statuses,
    reconcile_interrupted_runs,
    reconcile_orphaned_task_runs,
)

app = FastAPI(title="Manifestation Board API")

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
app.include_router(chats.router)
app.include_router(labels.router)
app.include_router(settings.router)
app.include_router(tools.router)


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
    close_client()


@app.get("/api/health")
async def health():
    return {"status": "ok"}
