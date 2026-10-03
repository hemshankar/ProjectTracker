"""Last-resort local file (JSON Lines) for events the outbox itself could not store."""
import json
import logging
import os

from .. import config
from .outbox import OutboxRepository

log = logging.getLogger(__name__)


class FallbackWriter:
    def __init__(self, path: str = ""):
        self._path = path or config.USAGE_FALLBACK_PATH

    def append(self, event: dict) -> None:
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")


class FallbackReplayer:
    def __init__(self, repo: OutboxRepository, path: str = ""):
        self._repo, self._path = repo, path or config.USAGE_FALLBACK_PATH

    async def replay(self) -> int:
        """Enqueue every saved event (idempotent), then delete the file. Returns events read."""
        if not os.path.exists(self._path):
            return 0
        count = 0
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    await self._repo.enqueue(json.loads(line))
                    count += 1
        os.remove(self._path)
        log.info("replayed %d usage event(s) from fallback file", count)
        return count
