"""Top-level API routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, calls, devices, files, friends, groups, keys, messages, moments, sessions, users


api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(devices.router, prefix="/devices", tags=["devices"])
api_router.include_router(keys.router, prefix="/keys", tags=["keys"])
api_router.include_router(calls.router, prefix="/calls", tags=["calls"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(friends.router, prefix="/friends", tags=["friends"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(messages.router, tags=["messages"])
api_router.include_router(groups.router, prefix="/groups", tags=["groups"])
api_router.include_router(moments.router, prefix="/moments", tags=["moments"])
api_router.include_router(files.router, tags=["files"])
