from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .database import boards_collection, ensure_indexes
from .routers import agents, auth, board_shares, boards, chats, settings, tools
from .seed import default_boards
from .task_state import (
    migrate_legacy_board_statuses,
    migrate_legacy_task_statuses,
    reconcile_interrupted_runs,
)

app = FastAPI(title="Scatterboard API")

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
    # Recover boards a prior process left "running"/"queued" mid-task — see
    # reconcile_interrupted_runs for why nothing else ever revisits them.
    await reconcile_interrupted_runs()


@app.get("/api/health")
async def health():
    return {"status": "ok"}
