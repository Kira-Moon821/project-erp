"""请求/响应模型（Pydantic v2）。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 认证
class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserBrief(ORMModel):
    user_id: int
    username: str
    full_name: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserBrief


# --------------------------------------------------------------------------- ERP 主体
class ProductBrief(ORMModel):
    product_id: int
    sku: str
    product_name: str
    category: str
    brand: str
    unit: str
    unit_cost: float
    list_price: float
    status: str


class CustomerBrief(ORMModel):
    customer_id: int
    customer_name: str
    industry: str
    region: str
    city: str
    tier: str
    channel: str
    customer_manager_id: int
    status: str


class SalesOrderItemIn(BaseModel):
    product_id: int
    qty: int = Field(gt=0, le=10000)
    discount_rate: float = Field(default=0.0, ge=0, le=0.35)


class SalesOrderIn(BaseModel):
    customer_id: int
    employee_id: Optional[int] = None
    items: List[SalesOrderItemIn] = Field(min_length=1)
    channel: Optional[str] = None
    remark: Optional[str] = Field(default=None, max_length=200)


class SalesOrderOut(BaseModel):
    order_id: int
    order_no: str
    customer_id: int
    net_amount: float
    gross_profit: float
    status: str
    created_at: Optional[datetime] = None


class Paginated(BaseModel):
    total: int
    page: int
    size: int
    items: List[Any]


# --------------------------------------------------------------------------- 看板与分析
class KpiCard(BaseModel):
    key: str
    label: str
    value: float
    unit: str = ""
    comparison: Optional[float] = None       # 与对比期的差异
    comparison_label: Optional[str] = None
    comparison_unit: str = "%"               # 比率类指标用 pp（百分点），避免「毛利率涨了 3%」的歧义
    hint: Optional[str] = None


class SummaryResponse(BaseModel):
    period: Dict[str, str]
    kpis: List[KpiCard]
    monthly: List[Dict[str, Any]] = []       # 月度 KPI 序列，供卡片迷你趋势线使用
    generated_at: str


class TrendPoint(BaseModel):
    period: str
    revenue: float
    orders: int
    gross_profit: float
    yoy_pct: Optional[float] = None
    mom_pct: Optional[float] = None


class NameValue(BaseModel):
    name: str
    value: float
    extra: Optional[Dict[str, Any]] = None


class FunnelStage(BaseModel):
    stage: str
    count: int
    conversion_from_prev: Optional[float] = None
    avg_cycle_days: Optional[float] = None


class Insight(BaseModel):
    code: str
    severity: str            # info / warning / critical
    title: str
    detail: str
    metric: Optional[Dict[str, Any]] = None
    evidence_sql: Optional[str] = None
    suggestion: Optional[str] = None
