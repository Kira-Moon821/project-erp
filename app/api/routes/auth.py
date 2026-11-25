"""认证路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import SysUser
from app.db.session import get_db
from app.schemas.models import LoginRequest, RefreshRequest, TokenResponse, UserBrief
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=TokenResponse, summary="登录换取访问令牌与刷新令牌")
def login(payload: LoginRequest, session: Session = Depends(get_db)) -> TokenResponse:
    result = auth_service.login(session, payload.username, payload.password)
    session.commit()          # 刷新令牌必须落库，否则轮换时找不到记录
    return TokenResponse(**result)


@router.post("/refresh", response_model=TokenResponse, summary="刷新令牌轮换")
def refresh(payload: RefreshRequest, session: Session = Depends(get_db)) -> TokenResponse:
    result = auth_service.refresh(session, payload.refresh_token)
    session.commit()          # 吊销旧令牌 + 写入新令牌
    return TokenResponse(**result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="吊销刷新令牌")
def logout(payload: RefreshRequest, session: Session = Depends(get_db)) -> None:
    auth_service.logout(session, payload.refresh_token)
    session.commit()


@router.get("/me", response_model=UserBrief, summary="当前用户信息")
def me(user: SysUser = Depends(get_current_user)) -> UserBrief:
    return UserBrief.model_validate(user)
