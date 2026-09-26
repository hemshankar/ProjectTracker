from motor.motor_asyncio import AsyncIOMotorClient

from . import config

_client = AsyncIOMotorClient(config.MONGO_URI)
db = _client[config.MONGO_DB_NAME]
boards_collection = db["boards"]
