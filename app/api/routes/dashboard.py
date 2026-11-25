"""看板与分析路由。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.config import get_settings
from app.db.models import SysUser
from app.db.session import get_db
from app.repositories import analytics_repo
from app.schemas.models import Insight, KpiCard
from app.services import insight_service

router = APIRouter(tags=["看板与分析"])


def _period(start: Optional[str] = None, end: Optional[str] = None) -> tuple[date, date]:
    """默认展示最近 12 个月（与「上一个 12 个月」对比，同比才有意义）。"""
    settings = get_settings()
    e = date.fromisoformat(end) if end else date.fromisoformat(settings.seed_end_date)
    if start:
        s = date.fromisoformat(start)
    else:
        ym = e.year * 12 + (e.month - 1) - 11
        s = date(ym // 12, ym % 12 + 1, 1)
    return s, e


@router.get("/dashboard/summary", summary="经营总览 KPI")
def dashboard_summary(
    start: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    session: Session = Depends(get_db),
    _user: SysUser = Depends(require_permission("read")),
) -> Dict[str, Any]:
    s, e = _period(start, end)
    kpi = analytics_repo.kpis(session, s, e)
    inv = analytics_repo.inventory_health(session)
    # 窗口 ≤ 1 年时是同比；跨年窗口则对比「紧邻的等长周期」
    cmp_label = "同比" if (e - s).days <= 366 else "较上一等长周期"

    def pct(cur: float, prev: float) -> Optional[float]:
        """比率变化：相对对比期的百分比涨跌幅。"""
        return (cur - prev) / prev * 100 if prev else None

    def pp(cur: float, prev: float) -> Optional[float]:
        """比率类指标（毛利率、折扣率）用百分点差，避免「涨了 3%」的口径歧义。"""
        return (cur - prev) * 100 if prev else None

    cards = [
        KpiCard(key="revenue", label="营收", value=kpi["revenue"], unit="元",
                comparison=pct(kpi["revenue"], kpi["prev_revenue"]), comparison_label=cmp_label),
        KpiCard(key="orders", label="订单数", value=kpi["orders"], unit="单",
                comparison=pct(kpi["orders"], kpi["prev_orders"]), comparison_label=cmp_label),
        KpiCard(key="customers", label="成交客户数", value=kpi["customers"], unit="家",
                comparison=pct(kpi["customers"], kpi["prev_customers"]), comparison_label=cmp_label),
        KpiCard(key="aov", label="客单价", value=kpi["aov"], unit="元",
                comparison=pct(kpi["aov"], kpi["prev_aov"]), comparison_label=cmp_label),
        KpiCard(key="gross_margin", label="毛利率", value=kpi["gross_margin"] * 100, unit="%",
                comparison=pp(kpi["gross_margin"], kpi["prev_gross_margin"]),
                comparison_label=cmp_label, comparison_unit="pp"),
        KpiCard(key="discount_rate", label="折扣率", value=kpi["discount_rate"] * 100, unit="%",
                comparison=pp(kpi["discount_rate"], kpi["prev_discount_rate"]),
                comparison_label=cmp_label, comparison_unit="pp"),
        KpiCard(key="inventory_value", label="期末库存金额", value=inv["inventory_value"], unit="元",
                hint=f"周转 {inv['turnover_days']} 天"),
        KpiCard(key="shortage_skus", label="低于安全库存 SKU", value=inv["shortage_skus"], unit="个",
                hint=f"共 {inv['sku_count']} 个 SKU"),
    ]
    return {"period": {"start": s.isoformat(), "end": e.isoformat()},
            "kpis": [c.model_dump() for c in cards],
            "monthly": analytics_repo.kpi_monthly(session, s, e),
            "generated_at": datetime.now().isoformat(timespec="seconds")}


@router.get("/dashboard/sales-trend", summary="月度营收趋势（同比/环比）")
def sales_trend(
    start: Optional[str] = None, end: Optional[str] = None,
    session: Session = Depends(get_db),
    _user: SysUser = Depends(require_permission("read")),
) -> List[Dict[str, Any]]:
    s, e = _period(start, end)
    return analytics_repo.sales_trend(session, s, e)


@router.get("/dashboard/top-customers", summary="Top 客户")
def top_customers(limit: int = Query(10, le=50), start: Optional[str] = None, end: Optional[str] = None,
                   session: Session = Depends(get_db),
                   _user: SysUser = Depends(require_permission("read"))) -> List[Dict[str, Any]]:
    s, e = _period(start, end)
    return analytics_repo.top_customers(session, s, e, limit)


@router.get("/dashboard/top-products", summary="Top 商品")
def top_products(limit: int = Query(10, le=50), start: Optional[str] = None, end: Optional[str] = None,
                  session: Session = Depends(get_db),
                  _user: SysUser = Depends(require_permission("read"))) -> List[Dict[str, Any]]:
    s, e = _period(start, end)
    return analytics_repo.top_products(session, s, e, limit)


@router.get("/dashboard/breakdown/{dimension}", summary="按行业/区域/渠道/团队拆解")
def breakdown(dimension: str, start: Optional[str] = None, end: Optional[str] = None,
              session: Session = Depends(get_db),
              _user: SysUser = Depends(require_permission("read"))) -> List[Dict[str, Any]]:
    from app.db.models import DimCustomer, DimEmployee

    s, e = _period(start, end)
    mapping = {
        "industry": (DimCustomer, DimCustomer.industry),
        "region": (DimCustomer, DimCustomer.region),
        "channel": (DimCustomer, DimCustomer.channel),
        "tier": (DimCustomer, DimCustomer.tier),
        "team": (DimCustomer, None),
    }
    if dimension == "team":
        # 团队维度按销售员 → 团队，需要走员工表
        from sqlalchemy import func, select
        from app.db.models import FactSalesOrder
        stmt = (select(DimEmployee.team, func.sum(FactSalesOrder.net_amount),
                       func.sum(FactSalesOrder.gross_profit), func.count(FactSalesOrder.order_id))
                .select_from(FactSalesOrder)
                .join(DimEmployee, FactSalesOrder.employee_id == DimEmployee.employee_id)
                .where(FactSalesOrder.status == "已完成")
                .group_by(DimEmployee.team))
        for cond in [FactSalesOrder.order_date_id >= int(s.strftime("%Y%m%d")),
                     FactSalesOrder.order_date_id <= int(e.strftime("%Y%m%d"))]:
            stmt = stmt.where(cond)
        return [{"name": r[0], "revenue": round(float(r[1]), 2), "gross_profit": round(float(r[2]), 2),
                 "orders": int(r[3])} for r in session.execute(stmt).all()]
    if dimension not in mapping:
        from app.core.errors import BusinessRuleError
        raise BusinessRuleError(f"不支持的维度：{dimension}", {"supported": list(mapping)})
    model, col = mapping[dimension]
    return analytics_repo.dimension_breakdown(session, model, col, s, e)


@router.get("/dashboard/funnel", summary="线索 → 商机 → 成单漏斗")
def funnel(start: Optional[str] = None, end: Optional[str] = None,
           session: Session = Depends(get_db),
           _user: SysUser = Depends(require_permission("read"))) -> List[Dict[str, Any]]:
    s, e = _period(start, end)
    return analytics_repo.funnel(session, s, e)


@router.get("/dashboard/inventory-health", summary="库存健康度")
def inventory_health(session: Session = Depends(get_db),
                     _user: SysUser = Depends(require_permission("read"))) -> Dict[str, Any]:
    return analytics_repo.inventory_health(session)


@router.get("/analytics/ai-value", summary="AI 价值量化（商机/工单/助手三组对照）")
def ai_value(start: Optional[str] = None, end: Optional[str] = None,
             session: Session = Depends(get_db),
             _user: SysUser = Depends(require_permission("analytics"))) -> Dict[str, Any]:
    s, e = _period(start, end)
    return analytics_repo.ai_value(session, s, e)


@router.get("/analytics/rfm", summary="客户 RFM 分层")
def rfm(as_of: Optional[str] = None, session: Session = Depends(get_db),
        _user: SysUser = Depends(require_permission("analytics"))) -> List[Dict[str, Any]]:
    settings = get_settings()
    day = date.fromisoformat(as_of) if as_of else date.fromisoformat(settings.seed_end_date)
    return analytics_repo.rfm(session, day)


@router.get("/analytics/marketing", summary="营销渠道效率（CAC/ROAS）")
def marketing(start: Optional[str] = None, end: Optional[str] = None,
              session: Session = Depends(get_db),
              _user: SysUser = Depends(require_permission("analytics"))) -> List[Dict[str, Any]]:
    s, e = _period(start, end)
    return analytics_repo.marketing_efficiency(session, s, e)


@router.get("/ai/insights", response_model=List[Insight], summary="自动经营洞察（每条附证据 SQL）")
def insights(start: Optional[str] = None, end: Optional[str] = None,
             session: Session = Depends(get_db),
             _user: SysUser = Depends(require_permission("analytics"))) -> List[Dict[str, Any]]:
    s, e = _period(start, end)
    return insight_service.build_insights(session, s, e)
