import hmac

from fastapi import Header, HTTPException

from . import config


async def require_internal_key(x_internal_key: str = Header(default="")) -> None:
    """Shared-secret check for monolith -> service calls. Fails closed when unset."""
    expected = config.INTERNAL_SERVICE_KEY
    if not expected or not hmac.compare_digest(x_internal_key, expected):
        raise HTTPException(status_code=401, detail="Invalid internal service key")
