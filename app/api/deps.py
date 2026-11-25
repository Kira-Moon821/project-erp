"""API 依赖：认证、RBAC、分页、限流。"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthError, PermissionError_
from app.core.security import decode_access_token
from app.db.models import SysUser
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)

# 角色 → 权限集合
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"read", "write", "analytics", "admin"},
    "analyst": {"read", "analytics"},
    "sales": {"read", "write"},
    "viewer": {"read"},
}


class TokenBucket:
    """按 IP 的令牌桶限流：内存实现，单实例足够，生产可换 Redis。"""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= self.per_minute:
            return False
        bucket.append(now)
        return True


rate_limiter = TokenBucket(get_settings().rate_limit_per_minute)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_db),
) -> SysUser:
    if credentials is None or not credentials.credentials:
        raise AuthError("缺少访问令牌")
    payload = decode_access_token(credentials.credentials)
    user = session.get(SysUser, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthError("用户不存在或已停用")
    return user


def require_permission(permission: str) -> Callable:
    """RBAC 依赖工厂：require_permission('write')。"""

    def _checker(user: SysUser = Depends(get_current_user)) -> SysUser:
        perms = ROLE_PERMISSIONS.get(user.role, set())
        if permission not in perms:
            raise PermissionError_(f"当前角色（{user.role}）无权执行该操作", {"required": permission})
        return user

    return _checker


def pagination(page: int = 1, size: int = 20) -> tuple[int, int]:
    page = max(1, page)
    size = max(1, min(size, 200))
    return page, size


def client_key(request: Request) -> str:
    """限流键：优先取反向代理传来的真实 IP（仅可信代理场景使用该头）。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> None:
    if not rate_limiter.allow(client_key(request)):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="请求过于频繁，请稍后再试")
