"""认证与授权：短时效访问令牌 + 服务端刷新令牌 + RBAC。

- 口令使用 PBKDF2-HMAC-SHA256（标准库实现，无原生编译依赖）；
- 访问令牌 15 分钟过期，刷新令牌服务端存储（可吊销）；
- 令牌不落 localStorage 的要求由前端约定（前端存内存），后端只签发。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt

from app.core.config import get_settings
from app.core.errors import AuthError

ALGORITHM = None  # 由 settings 决定


def get_algorithm() -> str:
    return get_settings().jwt_algorithm


def hash_password(password: str, iterations: Optional[int] = None) -> str:
    settings = get_settings()
    iterations = iterations or settings.password_hash_iterations
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(expected, actual)
    except (ValueError, TypeError):
        return False


def _encode(payload: Dict[str, Any]) -> str:
    settings = get_settings()
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str, expected_type: str) -> Dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("令牌已过期，请刷新或重新登录", {"type": expected_type}) from exc
    except jwt.PyJWTError as exc:
        raise AuthError("令牌无效", {"type": expected_type}) from exc
    if payload.get("typ") != expected_type:
        raise AuthError("令牌类型不匹配", {"type": expected_type})
    return payload


def create_access_token(user_id: int, username: str, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "typ": "access",
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    return _encode(payload)


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """返回 (token, jti, 过期时间)；jti 需写入服务端表以便吊销。"""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.refresh_token_ttl_days)
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "typ": "refresh",
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return _encode(payload), jti, expires_at


def decode_access_token(token: str) -> Dict[str, Any]:
    return _decode(token, "access")


def decode_refresh_token(token: str) -> Dict[str, Any]:
    return _decode(token, "refresh")
