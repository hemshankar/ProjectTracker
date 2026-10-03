import time
from typing import Any, Callable, Dict, Hashable, Tuple


class TtlCache:
    def __init__(self, ttl_seconds: float = 5.0, clock: Callable[[], float] = time.monotonic):
        self._ttl, self._clock = ttl_seconds, clock
        self._items: Dict[Hashable, Tuple[float, Any]] = {}

    def get(self, key: Hashable) -> Any:
        hit = self._items.get(key)
        if hit and self._clock() - hit[0] < self._ttl:
            return hit[1]
        self._items.pop(key, None)
        return None

    def put(self, key: Hashable, value: Any) -> None:
        if len(self._items) > 1000:
            self._items.clear()
        self._items[key] = (self._clock(), value)
