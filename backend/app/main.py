from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import boards_collection
from .routers import boards, chats
from .seed import default_boards

app = FastAPI(title="Scatterboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(boards.router)
app.include_router(chats.router)


@app.on_event("startup")
async def seed_if_empty():
    count = await boards_collection.count_documents({})
    if count == 0:
        await boards_collection.insert_many(default_boards())


@app.get("/api/health")
async def health():
    return {"status": "ok"}
