from contextlib import asynccontextmanager

from fastapi import FastAPI

from .container import get_container
from .database import ensure_indexes
from .errors import install_error_handlers
from .routers import events, export, health, rows, stats, summary


@asynccontextmanager
async def lifespan(_: FastAPI):
    container = get_container()
    await ensure_indexes(container.db)
    container.verifier.start()
    yield
    await container.verifier.stop()


app = FastAPI(title="Accounting Service", lifespan=lifespan)
install_error_handlers(app)

app.include_router(health.router)
app.include_router(events.router)
app.include_router(summary.router)
app.include_router(rows.router)
app.include_router(export.router)
app.include_router(stats.router)
