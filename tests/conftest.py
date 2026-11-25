# -*- coding: utf-8 -*-
"""
测试夹具：把数据库指向独立的临时 SQLite，避免污染开发库。

必须在导入 app.* 之前设置环境变量 —— settings 用 lru_cache 缓存，
一旦第一次 get_settings() 被调用就固定了。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_DB = Path(tempfile.gettempdir()) / "erp_analytics_test.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()
for suffix in ("-shm", "-wal"):
    p = Path(str(_TEST_DB) + suffix)
    if p.exists():
        p.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ENVIRONMENT"] = "test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.seed import run_seed  # noqa: E402
from app.db.session import create_all, session_scope  # noqa: E402
from app.main import app  # noqa: E402
from app.core.config import get_settings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _seed_database():
    """整个测试会话共用一份已灌种子的测试库"""
    settings = get_settings()
    create_all()  # 先建表，seed 的 reset 逻辑依赖表已存在
    with session_scope() as s:
        run_seed(s, settings, reset=True)
    yield
    for p in [_TEST_DB, Path(str(_TEST_DB) + "-shm"), Path(str(_TEST_DB) + "-wal")]:
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _login(client: TestClient, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="session")
def admin_token(client) -> str:
    return _login(client, "admin", "Admin@123456")["access_token"]


@pytest.fixture(scope="session")
def analyst_token(client) -> str:
    return _login(client, "analyst", "Analyst@123456")["access_token"]


@pytest.fixture(scope="session")
def sales_token(client) -> str:
    return _login(client, "sales", "Sales@123456")["access_token"]


@pytest.fixture(scope="session")
def viewer_token(client) -> str:
    return _login(client, "viewer", "Viewer@123456")["access_token"]


@pytest.fixture()
def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
