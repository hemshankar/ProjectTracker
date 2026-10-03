from fastapi import APIRouter

from . import actions, audit, auth, credentials, providers, test

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(auth.router)
router.include_router(providers.router)
router.include_router(actions.router)
router.include_router(test.router)
router.include_router(credentials.router)
router.include_router(audit.router)
