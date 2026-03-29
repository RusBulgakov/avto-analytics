"""
app/api/v1/router.py — Главный роутер v1
"""
from fastapi import APIRouter

from app.api.v1.endpoints import analytics, auth

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(analytics.router)
