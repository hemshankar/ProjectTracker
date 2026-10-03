from contextlib import asynccontextmanager

from fastapi import FastAPI

from .container import get_container
from .database import ensure_indexes
from .errors import install_error_handlers
from .routers.admin import router as admin_router
from .routers import connections, execute, health, providers, webhooks


@asynccontextmanager
async def lifespan(_: FastAPI):
    container = get_container()
    await ensure_indexes(container.db)
    await container.providers.seed()
    await container.secrets.primary.load()
    yield


app = FastAPI(title="Integrations Service", lifespan=lifespan)
install_error_handlers(app)

app.include_router(health.router)
app.include_router(providers.router)
app.include_router(connections.router)
app.include_router(execute.router)
app.include_router(webhooks.router)
app.include_router(admin_router)

