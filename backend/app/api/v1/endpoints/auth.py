"""
app/api/v1/endpoints/auth.py — Регистрация, логин, профиль
"""
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.core.database import DBSession
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, get_current_user,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(data: RegisterIn):
    if len(data.password) < 8:
        raise HTTPException(400, "Пароль должен содержать минимум 8 символов")
    async with DBSession() as conn:
        existing = await conn.fetchval("SELECT id FROM users WHERE email = $1", data.email)
        if existing:
            raise HTTPException(400, "Email уже зарегистрирован")
        user_id = await conn.fetchval(
            "INSERT INTO users (email, hashed_password, full_name) VALUES ($1, $2, $3) RETURNING id",
            data.email, hash_password(data.password), data.full_name,
        )
    token_data = {"sub": str(user_id), "email": data.email}
    return TokenOut(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post("/login", response_model=TokenOut)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    async with DBSession() as conn:
        user = await conn.fetchrow(
            "SELECT id, hashed_password, is_active FROM users WHERE email = $1", form.username
        )
    if not user or not verify_password(form.password, user["hashed_password"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    if not user["is_active"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт заблокирован")
    token_data = {"sub": str(user["id"]), "email": form.username}
    return TokenOut(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.get("/me", summary="Мой профиль")
async def me(current_user: dict = Depends(get_current_user)):
    """Возвращает профиль текущего пользователя с данными о подписке."""
    async with DBSession() as conn:
        user = await conn.fetchrow(
            "SELECT id, email, full_name, phone, created_at FROM users WHERE id = $1",
            current_user["id"],
        )
        subscription = await conn.fetchrow("""
            SELECT sp.name AS plan, sp.display_name, us.expires_at
            FROM user_subscriptions us
            JOIN subscription_plans sp ON sp.id = us.plan_id
            WHERE us.user_id = $1 AND us.is_active = TRUE
              AND (us.expires_at IS NULL OR us.expires_at > NOW())
            ORDER BY us.started_at DESC LIMIT 1
        """, current_user["id"])
    return {
        **dict(user),
        "subscription": dict(subscription) if subscription else {"plan": "free"},
    }
