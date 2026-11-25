# -*- coding: utf-8 -*-
"""
ERP 经营分析实验室 · API 冒烟测试

覆盖：
  · 健康检查与就绪检查
  · 登录 / 令牌轮换 / 吊销 / 错误口令
  · RBAC：viewer 下单被拒、sales 可下单
  · 业务规则：库存不足下单被拒（422）
  · 分析端点返回结构与口径
  · 分页与筛选
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------- 健康检查
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "healthy")


def test_ready(client):
    r = client.get("/ready")
    assert r.status_code == 200


def test_home_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "ERP" in r.text


# ---------------------------------------------------------------- 鉴权
def test_login_success(client):
    r = client.post("/api/auth/login",
                    json={"username": "analyst", "password": "Analyst@123456"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"].lower() == "bearer"


def test_login_wrong_password(client):
    r = client.post("/api/auth/login",
                    json={"username": "analyst", "password": "wrong-password"})
    assert r.status_code == 401


def test_login_unknown_user(client):
    r = client.post("/api/auth/login",
                    json={"username": "no-such-user", "password": "wrongpass"})
    assert r.status_code == 401


def test_protected_endpoint_requires_token(client):
    r = client.get("/api/dashboard/summary")
    assert r.status_code == 401


def test_me_returns_current_user(client, analyst_token):
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {analyst_token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "analyst"


def test_refresh_rotates_and_revokes_old_token(client):
    login = client.post("/api/auth/login",
                        json={"username": "viewer", "password": "Viewer@123456"}).json()
    old_refresh = login["refresh_token"]

    r = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_refresh = r.json()["refresh_token"]
    assert new_refresh != old_refresh

    # 旧刷新令牌应立即失效（轮换即吊销）
    r2 = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 401

    # 新刷新令牌可用
    r3 = client.post("/api/auth/refresh", json={"refresh_token": new_refresh})
    assert r3.status_code == 200


def test_logout_revokes_refresh_token(client):
    login = client.post("/api/auth/login",
                        json={"username": "viewer", "password": "Viewer@123456"}).json()
    refresh = login["refresh_token"]
    access = login["access_token"]

    r = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {access}"},
                    json={"refresh_token": refresh})
    assert r.status_code in (200, 204)

    r2 = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401


# ---------------------------------------------------------------- RBAC
def test_viewer_cannot_create_order(client, viewer_token):
    payload = {
        "customer_id": 1,
        "items": [{"product_id": 1, "qty": 1}],
    }
    r = client.post("/api/sales-orders", json=payload,
                    headers={"Authorization": f"Bearer {viewer_token}"})
    assert r.status_code == 403


def test_analyst_can_read_dashboard(client, analyst_token):
    r = client.get("/api/dashboard/summary",
                   headers={"Authorization": f"Bearer {analyst_token}"})
    assert r.status_code == 200
    body = r.json()
    assert "kpis" in body or "revenue" in body or "items" in body


# ---------------------------------------------------------------- 业务规则
def test_create_order_rejects_insufficient_stock(client, sales_token):
    """库存不足应返回 422，且错误体里带缺货明细"""
    payload = {
        "customer_id": 1,
        "items": [{"product_id": 1, "qty": 10_000_000}],
    }
    r = client.post("/api/sales-orders", json=payload,
                    headers={"Authorization": f"Bearer {sales_token}"})
    assert r.status_code == 422
    body = r.json()
    assert "error" in body
    assert "request_id" in body["error"]


def test_create_order_success(client, sales_token):
    """正常下单应返回 201，并能在订单列表里查到"""
    payload = {
        "customer_id": 1,
        "items": [{"product_id": 1, "qty": 1}],
    }
    r = client.post("/api/sales-orders", json=payload,
                    headers={"Authorization": f"Bearer {sales_token}"})
    assert r.status_code == 201, r.text
    body = r.json()
    order_id = body.get("order_id") or body.get("id")
    assert order_id

    detail = client.get(f"/api/sales-orders/{order_id}",
                        headers={"Authorization": f"Bearer {sales_token}"})
    assert detail.status_code == 200


# ---------------------------------------------------------------- 分析端点
@pytest.mark.parametrize("path", [
    "/api/dashboard/summary",
    "/api/dashboard/sales-trend",
    "/api/dashboard/top-customers",
    "/api/dashboard/top-products",
    "/api/dashboard/funnel",
    "/api/dashboard/inventory-health",
    "/api/analytics/ai-value",
    "/api/analytics/rfm",
    "/api/analytics/marketing",
    "/api/ai/insights",
])
def test_analytics_endpoints_ok(client, analyst_token, path):
    r = client.get(path, headers={"Authorization": f"Bearer {analyst_token}"})
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
    assert r.json() is not None


def test_breakdown_dimension(client, analyst_token):
    for dim in ("industry", "region", "channel", "team"):
        r = client.get(f"/api/dashboard/breakdown/{dim}",
                       headers={"Authorization": f"Bearer {analyst_token}"})
        assert r.status_code == 200, f"{dim} -> {r.status_code}"


def test_erp_lists_paginated(client, analyst_token):
    for path in ("/api/products", "/api/customers", "/api/sales-orders"):
        r = client.get(path, headers={"Authorization": f"Bearer {analyst_token}"})
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "total" in body
        assert len(body["items"]) <= body.get("page_size", 20)


def test_inventory_latest(client, analyst_token):
    r = client.get("/api/inventory", headers={"Authorization": f"Bearer {analyst_token}"})
    assert r.status_code == 200
    assert isinstance(r.json(), (list, dict))


# ---------------------------------------------------------------- 数据质量
def test_inventory_reconciliation_is_zero(client, analyst_token):
    """库存收发存对账：期初+入库-出库-报废 = 月末快照，差异应为 0"""
    from sqlalchemy import text
    from app.db.session import build_engine
    from app.core.config import get_settings

    eng = build_engine(get_settings())
    sql = """
    WITH last_snap AS (
        SELECT MAX(d.full_date) AS d
        FROM fact_inventory_snapshot s JOIN dim_date d ON d.date_id = s.date_id
    )
    SELECT
      (SELECT IFNULL(SUM(t.qty), 0)
         FROM fact_inventory_transaction t JOIN dim_date d ON d.date_id = t.date_id
        WHERE d.full_date <= (SELECT d FROM last_snap))
    - (SELECT IFNULL(SUM(s.on_hand_qty), 0)
         FROM fact_inventory_snapshot s JOIN dim_date d ON d.date_id = s.date_id
        WHERE d.full_date = (SELECT d FROM last_snap))
    """
    with eng.connect() as c:
        diff = c.execute(text(sql)).scalar()
    assert abs(float(diff)) < 1e-6, f"库存对账差异不为 0：{diff}"


def test_no_negative_stock(client):
    from sqlalchemy import text
    from app.db.session import build_engine
    from app.core.config import get_settings

    eng = build_engine(get_settings())
    with eng.connect() as c:
        n = c.execute(text(
            "SELECT COUNT(*) FROM fact_inventory_snapshot WHERE on_hand_qty < 0")).scalar()
    assert n == 0, f"存在 {n} 条负库存快照"
