"""认证服务：登录、刷新令牌轮换、吊销。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    verify_password,
)
from app.db.models import SysRefreshToken, SysUser


def _user_brief(user: SysUser) -> Dict[str, Any]:
    return {"user_id": user.user_id, "username": user.username, "full_name": user.full_name, "role": user.role}


def login(session: Session, username: str, password: str) -> Dict[str, Any]:
    user = session.execute(select(SysUser).where(SysUser.username == username)).scalar_one_or_none()
    # 用户不存在与密码错误返回同一错误，避免账号枚举
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthError("用户名或密码错误")
    return _issue_tokens(session, user)


def refresh(session: Session, refresh_token: str) -> Dict[str, Any]:
    payload = decode_refresh_token(refresh_token)
    jti = payload.get("jti")
    stored = session.get(SysRefreshToken, jti)
    if stored is None or stored.revoked:
        raise AuthError("刷新令牌已失效，请重新登录")
    if stored.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        raise AuthError("刷新令牌已过期，请重新登录")
    user = session.get(SysUser, stored.user_id)
    if user is None or not user.is_active:
        raise AuthError("用户不存在或已停用")
    # 轮换：旧刷新令牌立即吊销
    stored.revoked = 1
    session.flush()
    return _issue_tokens(session, user)


def logout(session: Session, refresh_token: str) -> None:
    try:
        payload = decode_refresh_token(refresh_token)
    except AuthError:
        return
    stored = session.get(SysRefreshToken, payload.get("jti"))
    if stored is not None:
        stored.revoked = 1
        session.flush()


def _issue_tokens(session: Session, user: SysUser) -> Dict[str, Any]:
    settings = get_settings()
    access_token = create_access_token(user.user_id, user.username, user.role)
    refresh_token, jti, expires_at = create_refresh_token(user.user_id)
    session.add(SysRefreshToken(jti=jti, user_id=user.user_id, expires_at=expires_at, revoked=0))
    session.flush()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl_minutes * 60,
        "user": _user_brief(user),
    }
