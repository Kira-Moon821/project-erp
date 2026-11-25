"""分析类仓储层：只做数据访问与聚合，不含业务规则。

所有营收类指标统一过滤 status = '已完成'（口径见 docs/数据字典与业务口径.md）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Select, case, distinct, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DimCustomer,
    DimDate,
    DimEmployee,
    DimProduct,
    FactAiUsage,
    FactCustomerTicket,
    FactInventorySnapshot,
    FactLeadOpportunity,
    FactMarketingSpend,
    FactSalesOrder,
    FactSalesOrderItem,
)

COMPLETED = "已完成"


def _date_filter(column, start: Optional[date], end: Optional[date]) -> List[Any]:
    conds = []
    if start:
        conds.append(column >= int(start.strftime("%Y%m%d")))
    if end:
        conds.append(column <= int(end.strftime("%Y%m%d")))
    return conds


def order_scope(start: Optional[date], end: Optional[date]) -> Select:
    """已完成订单 + 业务窗口过滤，作为所有销售分析的统一入口。"""
    stmt = select(FactSalesOrder).where(FactSalesOrder.status == COMPLETED)
    for cond in _date_filter(FactSalesOrder.order_date_id, start, end):
        stmt = stmt.where(cond)
    return stmt


def kpis(session: Session, start: date, end: date) -> Dict[str, Any]:
    """核心 KPI：营收、订单数、客户数、AOV、毛利率。"""
    stmt = select(
        func.coalesce(func.sum(FactSalesOrder.net_amount), 0),
        func.coalesce(func.sum(FactSalesOrder.gross_profit), 0),
        func.coalesce(func.sum(FactSalesOrder.discount_amount), 0),
        func.coalesce(func.sum(FactSalesOrder.cost_amount), 0),
        func.coalesce(func.sum(case((FactSalesOrder.status == COMPLETED, 1), else_=0)), 0),
        func.count(distinct(case((FactSalesOrder.status == COMPLETED, FactSalesOrder.customer_id)))),
        func.coalesce(func.sum(case((FactSalesOrder.payment_status == "未付款", FactSalesOrder.net_amount), else_=0)), 0),
    ).where(FactSalesOrder.status == COMPLETED)
    for cond in _date_filter(FactSalesOrder.order_date_id, start, end):
        stmt = stmt.where(cond)
    revenue, profit, discount, cost, orders, customers, unpaid = session.execute(stmt).one()

    # 同比基线：取「紧邻的等长周期」作为对比期
    # （窗口为 24 个月时，对比期就是上一个 12 个月，比同日期去年更合理）
    span = (end - start).days
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span)
    prev = kpis_raw(session, prev_start, prev_end)

    return {
        "revenue": float(revenue),
        "gross_profit": float(profit),
        "discount_amount": float(discount),
        "cost": float(cost),
        "orders": int(orders),
        "customers": int(customers),
        "aov": round(float(revenue) / int(orders), 2) if orders else 0.0,
        "gross_margin": round(float(profit) / float(revenue), 4) if revenue else 0.0,
        "discount_rate": round(float(discount) / (float(revenue) + float(discount)), 4) if (revenue + discount) else 0.0,
        "unpaid_amount": float(unpaid),
        # 对比期（紧邻的等长周期）同口径指标，供 KPI 卡片计算涨跌幅
        "prev_revenue": prev["revenue"],
        "prev_orders": prev["orders"],
        "prev_profit": prev["gross_profit"],
        "prev_customers": prev["customers"],
        "prev_aov": prev["aov"],
        "prev_gross_margin": prev["gross_margin"],
        "prev_discount_rate": prev["discount_rate"],
    }


def kpis_raw(session: Session, start: date, end: date) -> Dict[str, Any]:
    """只算必须的聚合值，用于对比期（避免与主查询重复取数时带上明细开销）。"""
    stmt = select(
        func.coalesce(func.sum(FactSalesOrder.net_amount), 0),
        func.coalesce(func.sum(FactSalesOrder.gross_profit), 0),
        func.coalesce(func.sum(FactSalesOrder.discount_amount), 0),
        func.coalesce(func.sum(case((FactSalesOrder.status == COMPLETED, 1), else_=0)), 0),
        func.count(distinct(FactSalesOrder.customer_id)),
    ).where(FactSalesOrder.status == COMPLETED)
    for cond in _date_filter(FactSalesOrder.order_date_id, start, end):
        stmt = stmt.where(cond)
    revenue, profit, discount, orders, customers = session.execute(stmt).one()
    revenue, profit, discount = float(revenue), float(profit), float(discount)
    orders, customers = int(orders), int(customers)
    return {
        "revenue": revenue,
        "gross_profit": profit,
        "orders": orders,
        "customers": customers,
        "aov": round(revenue / orders, 2) if orders else 0.0,
        "gross_margin": round(profit / revenue, 4) if revenue else 0.0,
        "discount_rate": round(discount / (revenue + discount), 4) if (revenue + discount) else 0.0,
    }


def kpi_monthly(session: Session, start: date, end: date) -> List[Dict[str, Any]]:
    """按月拆解 6 个核心 KPI，只给前端画 KPI 卡片上的迷你趋势线（sparkline）用。"""
    stmt = (
        select(
            DimDate.year_month,
            func.coalesce(func.sum(FactSalesOrder.net_amount), 0),
            func.coalesce(func.sum(FactSalesOrder.gross_profit), 0),
            func.coalesce(func.sum(FactSalesOrder.discount_amount), 0),
            func.count(),
            func.count(distinct(FactSalesOrder.customer_id)),
        )
        .select_from(FactSalesOrder)
        .join(DimDate, FactSalesOrder.order_date_id == DimDate.date_id)
        .where(FactSalesOrder.status == COMPLETED)
        .group_by(DimDate.year_month)
        .order_by(DimDate.year_month)
    )
    for cond in _date_filter(FactSalesOrder.order_date_id, start, end):
        stmt = stmt.where(cond)

    out: List[Dict[str, Any]] = []
    for ym, revenue, profit, discount, orders, customers in session.execute(stmt).all():
        revenue, profit, discount = float(revenue), float(profit), float(discount or 0)
        orders, customers = int(orders), int(customers)
        out.append({
            "period": ym,
            "revenue": round(revenue, 2),
            "orders": orders,
            "customers": customers,
            "aov": round(revenue / orders, 2) if orders else 0.0,
            "gross_margin": round(profit / revenue * 100, 2) if revenue else 0.0,
            "discount_rate": round(discount / (revenue + discount) * 100, 2) if (revenue + discount) else 0.0,
        })
    return out


def sales_trend(session: Session, start: date, end: date) -> List[Dict[str, Any]]:
    """月度营收趋势 + 同比 + 环比。"""
    stmt = (
        select(
            DimDate.year_month,
            func.coalesce(func.sum(FactSalesOrder.net_amount), 0),
            func.coalesce(func.sum(FactSalesOrder.gross_profit), 0),
            func.coalesce(func.sum(case((FactSalesOrder.status == COMPLETED, 1), else_=0)), 0),
        )
        .select_from(FactSalesOrder)
        .join(DimDate, FactSalesOrder.order_date_id == DimDate.date_id)
        .where(FactSalesOrder.status == COMPLETED)
        .group_by(DimDate.year_month)
        .order_by(DimDate.year_month)
    )
    for cond in _date_filter(FactSalesOrder.order_date_id, start, end):
        stmt = stmt.where(cond)

    rows = session.execute(stmt).all()
    points = [{"period": r[0], "revenue": round(float(r[1]), 2), "gross_profit": round(float(r[2]), 2),
               "orders": int(r[3])} for r in rows]
    by_period = {p["period"]: p for p in points}

    for p in points:
        year, month = p["period"].split("-")
        prev_year = f"{int(year) - 1}-{month}"
        prev_month = f"{int(year) - 1}-{month}" if month == "12" else (
            f"{year}-{int(month) - 1:02d}" if int(month) > 1 else f"{int(year) - 1}-12")
        py = by_period.get(prev_year)
        pm = by_period.get(prev_month)
        p["yoy_pct"] = round((p["revenue"] - py["revenue"]) / py["revenue"] * 100, 2) if py and py["revenue"] else None
        p["mom_pct"] = round((p["revenue"] - pm["revenue"]) / pm["revenue"] * 100, 2) if pm and pm["revenue"] else None
    return points


def top_customers(session: Session, start: date, end: date, limit: int = 10) -> List[Dict[str, Any]]:
    stmt = (
        select(
            DimCustomer.customer_id, DimCustomer.customer_name, DimCustomer.tier, DimCustomer.industry,
            func.sum(FactSalesOrder.net_amount), func.sum(FactSalesOrder.gross_profit),
            func.count(FactSalesOrder.order_id), func.avg(FactSalesOrder.net_amount),
        )
        .select_from(FactSalesOrder)
        .join(DimCustomer, FactSalesOrder.customer_id == DimCustomer.customer_id)
        .where(FactSalesOrder.status == COMPLETED)
        .group_by(DimCustomer.customer_id, DimCustomer.customer_name, DimCustomer.tier, DimCustomer.industry)
        .order_by(func.sum(FactSalesOrder.net_amount).desc())
        .limit(limit)
    )
    for cond in _date_filter(FactSalesOrder.order_date_id, start, end):
        stmt = stmt.where(cond)
    return [{"customer_id": r[0], "customer_name": r[1], "tier": r[2], "industry": r[3],
             "revenue": round(float(r[4]), 2), "gross_profit": round(float(r[5]), 2),
             "orders": int(r[6]), "aov": round(float(r[7]), 2)} for r in session.execute(stmt).all()]


def top_products(session: Session, start: date, end: date, limit: int = 10) -> List[Dict[str, Any]]:
    stmt = (
        select(
            DimProduct.product_id, DimProduct.sku, DimProduct.product_name, DimProduct.category,
            func.sum(FactSalesOrderItem.qty),
            func.sum(FactSalesOrderItem.revenue_amount),
            func.sum(FactSalesOrderItem.revenue_amount - FactSalesOrderItem.cost_amount),
        )
        .select_from(FactSalesOrderItem)
        .join(FactSalesOrder, FactSalesOrderItem.order_id == FactSalesOrder.order_id)
        .join(DimProduct, FactSalesOrderItem.product_id == DimProduct.product_id)
        .where(FactSalesOrder.status == COMPLETED)
        .group_by(DimProduct.product_id, DimProduct.sku, DimProduct.product_name, DimProduct.category)
        .order_by(func.sum(FactSalesOrderItem.revenue_amount).desc())
        .limit(limit)
    )
    for cond in _date_filter(FactSalesOrder.order_date_id, start, end):
        stmt = stmt.where(cond)
    out = []
    for r in session.execute(stmt).all():
        revenue = float(r[5])
        profit = float(r[6])
        out.append({"product_id": r[0], "sku": r[1], "product_name": r[2], "category": r[3],
                    "qty": int(r[4]), "revenue": round(revenue, 2), "gross_profit": round(profit, 2),
                    "gross_margin": round(profit / revenue, 4) if revenue else 0.0})
    return out


def dimension_breakdown(session: Session, dim_model, dim_col, start: date, end: date) -> List[Dict[str, Any]]:
    """按任意维度（行业/区域/渠道/团队）拆解营收。"""
    stmt = (
        select(dim_col, func.sum(FactSalesOrder.net_amount), func.sum(FactSalesOrder.gross_profit),
               func.count(FactSalesOrder.order_id), func.count(distinct(FactSalesOrder.customer_id)))
        .select_from(FactSalesOrder)
        .join(dim_model, FactSalesOrder.customer_id == dim_model.customer_id)
        .where(FactSalesOrder.status == COMPLETED)
        .group_by(dim_col)
        .order_by(func.sum(FactSalesOrder.net_amount).desc())
    )
    for cond in _date_filter(FactSalesOrder.order_date_id, start, end):
        stmt = stmt.where(cond)
    return [{"name": r[0], "revenue": round(float(r[1]), 2), "gross_profit": round(float(r[2]), 2),
             "orders": int(r[3]), "customers": int(r[4])} for r in session.execute(stmt).all()]


def funnel(session: Session, start: date, end: date) -> List[Dict[str, Any]]:
    """线索 → 商机 → 成单漏斗（逐级转化 + 平均停留周期）。"""
    stmt = (
        select(
            FactLeadOpportunity.stage, func.count(FactLeadOpportunity.lead_id),
            func.avg(FactLeadOpportunity.cycle_days),
            func.sum(case((FactLeadOpportunity.stage == "成单", FactLeadOpportunity.actual_amount), else_=0)),
        )
        .where(FactLeadOpportunity.stage != "输单")
        .group_by(FactLeadOpportunity.stage)
    )
    for cond in _date_filter(FactLeadOpportunity.created_date_id, start, end):
        stmt = stmt.where(cond)
    order = ["线索", "需求确认", "方案演示", "商务谈判", "成单"]
    raw = {r[0]: (int(r[1]), float(r[2] or 0), float(r[3] or 0)) for r in session.execute(stmt).all()}
    out, prev_count = [], None
    for stage in order:
        count, cycle, amount = raw.get(stage, (0, 0.0, 0.0))
        out.append({
            "stage": stage, "count": count,
            "conversion_from_prev": round(count / prev_count * 100, 2) if prev_count else None,
            "avg_cycle_days": round(cycle, 1),
            "won_amount": round(amount, 2),
        })
        prev_count = count
    return out


def inventory_health(session: Session) -> Dict[str, Any]:
    """库存健康度：金额、周转天数、缺货 SKU、滞销 SKU。"""
    last_date = session.execute(select(func.max(FactInventorySnapshot.date_id))).scalar()
    if last_date is None:
        return {"snapshot_date": None, "inventory_value": 0, "turnover_days": 0, "shortage_skus": 0,
                "slow_moving_skus": 0, "sku_count": 0}

    inv_value = session.execute(
        select(func.coalesce(func.sum(FactInventorySnapshot.inventory_value), 0))
        .where(FactInventorySnapshot.date_id == last_date)
    ).scalar()
    shortage = session.execute(
        select(func.count())
        .select_from(FactInventorySnapshot)
        .where(FactInventorySnapshot.date_id == last_date,
               FactInventorySnapshot.on_hand_qty < FactInventorySnapshot.safety_stock)
    ).scalar()
    sku_count = session.execute(
        select(func.count(distinct(FactInventorySnapshot.product_id)))
        .where(FactInventorySnapshot.date_id == last_date)
    ).scalar()

    # 近 90 天动销与滞销（以快照日往前推 90 天为窗口）
    snapshot_date = date(int(str(last_date)[:4]), int(str(last_date)[4:6]), int(str(last_date)[6:]))
    window_start = int((snapshot_date - timedelta(days=90)).strftime("%Y%m%d"))
    sold_90d_cond = (
        select(FactSalesOrderItem.product_id)
        .join(FactSalesOrder, FactSalesOrderItem.order_id == FactSalesOrder.order_id)
        .where(FactSalesOrder.status == COMPLETED,
               FactSalesOrder.order_date_id >= window_start,
               FactSalesOrder.order_date_id <= last_date)
    )
    moving = session.execute(
        select(func.count(distinct(FactSalesOrderItem.product_id)))
        .select_from(FactSalesOrderItem)
        .join(FactSalesOrder, FactSalesOrderItem.order_id == FactSalesOrder.order_id)
        .where(FactSalesOrder.status == COMPLETED,
               FactSalesOrder.order_date_id >= window_start,
               FactSalesOrder.order_date_id <= last_date)
    ).scalar()
    slow = session.execute(
        select(func.count(distinct(FactInventorySnapshot.product_id)))
        .select_from(FactInventorySnapshot)
        .where(FactInventorySnapshot.date_id == last_date,
               FactInventorySnapshot.on_hand_qty > 0,
               ~FactInventorySnapshot.product_id.in_(sold_90d_cond))
    ).scalar()

    # 库存周转天数（成本口径）：期末库存金额 ÷ 日均销售成本
    daily_cost = session.execute(
        select(func.coalesce(func.sum(FactSalesOrder.cost_amount), 0))
        .where(FactSalesOrder.status == COMPLETED,
               FactSalesOrder.order_date_id >= window_start,
               FactSalesOrder.order_date_id <= last_date)
    ).scalar()
    turnover = round(float(inv_value) / (float(daily_cost) / 90), 1) if daily_cost else 0.0

    return {
        "snapshot_date": last_date,
        "inventory_value": round(float(inv_value), 2),
        "turnover_days": turnover,
        "shortage_skus": int(shortage or 0),
        "slow_moving_skus": int(slow or 0),
        "sku_count": int(sku_count or 0),
        "moving_skus_90d": int(moving or 0),
    }


def ai_value(session: Session, start: date, end: date) -> Dict[str, Any]:
    """AI 价值量化：商机、工单、助手使用三组对照。"""
    lead_stmt = select(
        FactLeadOpportunity.ai_assisted,
        func.count(FactLeadOpportunity.lead_id),
        func.avg(FactLeadOpportunity.win_probability),
        func.avg(FactLeadOpportunity.cycle_days),
        func.sum(case((FactLeadOpportunity.stage == "成单", 1), else_=0)),
        func.sum(FactLeadOpportunity.actual_amount),
    ).group_by(FactLeadOpportunity.ai_assisted)
    for cond in _date_filter(FactLeadOpportunity.created_date_id, start, end):
        lead_stmt = lead_stmt.where(cond)
    leads = {int(r[0]): {"count": int(r[1]), "avg_win_prob": round(float(r[2]), 4),
                         "avg_cycle_days": round(float(r[3]), 1), "won": int(r[4]),
                         "won_amount": round(float(r[5] or 0), 2)} for r in session.execute(lead_stmt).all()}

    ticket_stmt = select(
        FactCustomerTicket.ai_handled, func.count(FactCustomerTicket.ticket_id),
        func.avg(FactCustomerTicket.first_response_minutes), func.avg(FactCustomerTicket.resolution_hours),
        func.avg(FactCustomerTicket.satisfaction),
        func.sum(FactCustomerTicket.converted_to_opportunity),
    ).group_by(FactCustomerTicket.ai_handled)
    for cond in _date_filter(FactCustomerTicket.created_date_id, start, end):
        ticket_stmt = ticket_stmt.where(cond)
    tickets = {int(r[0]): {"count": int(r[1]), "avg_first_response_min": round(float(r[2]), 1),
                           "avg_resolution_hours": round(float(r[3]), 2),
                           "avg_satisfaction": round(float(r[4]), 2),
                           "converted": int(r[5])} for r in session.execute(ticket_stmt).all()}

    usage_stmt = select(
        func.coalesce(func.sum(FactAiUsage.query_count), 0),
        func.coalesce(func.sum(FactAiUsage.accepted_count), 0),
        func.coalesce(func.sum(FactAiUsage.minutes_saved), 0),
        func.count(distinct(FactAiUsage.employee_id)),
    )
    for cond in _date_filter(FactAiUsage.date_id, start, end):
        usage_stmt = usage_stmt.where(cond)
    q_total, a_total, minutes, users = session.execute(usage_stmt).one()

    return {
        "leads": leads,
        "tickets": tickets,
        "usage": {
            "queries": int(q_total), "accepted": int(a_total),
            "acceptance_rate": round(int(a_total) / int(q_total), 4) if q_total else 0,
            "minutes_saved": round(float(minutes), 1),
            "hours_saved": round(float(minutes) / 60, 1),
            "active_users": int(users),
        },
    }


def marketing_efficiency(session: Session, start: date, end: date) -> List[Dict[str, Any]]:
    stmt = (
        select(
            FactMarketingSpend.channel, func.sum(FactMarketingSpend.cost_amount),
            func.sum(FactMarketingSpend.leads_count), func.sum(FactMarketingSpend.revenue_attributed),
        )
        .group_by(FactMarketingSpend.channel)
        .order_by(func.sum(FactMarketingSpend.cost_amount).desc())
    )
    for cond in _date_filter(FactMarketingSpend.date_id, start, end):
        stmt = stmt.where(cond)
    out = []
    for r in session.execute(stmt).all():
        cost, leads, revenue = float(r[1]), int(r[2]), float(r[3])
        out.append({"channel": r[0], "cost": round(cost, 2), "leads": leads,
                    "revenue_attributed": round(revenue, 2),
                    "cac": round(cost / leads, 2) if leads else 0.0,
                    "roas": round(revenue / cost, 2) if cost else 0.0})
    return out


def rfm(session: Session, as_of: date) -> List[Dict[str, Any]]:
    """RFM 分层：R 距最近成交天数 / F 成交次数 / M 成交金额。"""
    stmt = (
        select(
            FactSalesOrder.customer_id,
            func.max(FactSalesOrder.order_date_id),
            func.count(FactSalesOrder.order_id),
            func.sum(FactSalesOrder.net_amount),
        )
        .where(FactSalesOrder.status == COMPLETED)
        .group_by(FactSalesOrder.customer_id)
    )
    rows = session.execute(stmt).all()
    as_of_id = int(as_of.strftime("%Y%m%d"))
    recency, freq, money = [], [], []
    for cid, last_date, cnt, amount in rows:
        r = as_of_id - int(last_date)
        recency.append(r)
        freq.append(int(cnt))
        money.append(float(amount))
    if not recency:
        return []
    r_cut = _quantile(recency, 0.75)
    f_cut = _quantile(freq, 0.50)
    m_cut = _quantile(money, 0.50)

    out = []
    for cid, last_date, cnt, amount in rows:
        r = as_of_id - int(last_date)
        f, m = int(cnt), float(amount)
        r_score = 5 if r <= r_cut else 3 if r <= r_cut * 2 else 1
        f_score = 5 if f >= f_cut * 2 else 4 if f >= f_cut * 1.5 else 3 if f >= f_cut else 2 if f >= f_cut / 2 else 1
        m_score = 5 if m >= m_cut * 2 else 4 if m >= m_cut * 1.5 else 3 if m >= m_cut else 2 if m >= m_cut / 2 else 1
        rfm_cell = f"{r_score}{f_score}{m_score}"
        if r_score >= 4 and f_score >= 4 and m_score >= 4:
            segment = "重要价值客户"
        elif r_score >= 4 and m_score >= 3:
            segment = "重要保持客户"
        elif r_score <= 2 and f_score >= 4:
            segment = "重要流失预警"
        elif r_score >= 4 and f_score <= 2:
            segment = "新客户"
        elif r_score <= 2 and f_score <= 2:
            segment = "沉睡客户"
        else:
            segment = "一般客户"
        out.append({"customer_id": cid, "recency_days": r, "frequency": f, "monetary": round(m, 2),
                    "r_score": r_score, "f_score": f_score, "m_score": m_score,
                    "rfm_cell": rfm_cell, "segment": segment})
    out.sort(key=lambda x: (-x["monetary"],))
    return out


def _quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(q * (len(ordered) - 1)))))
    return float(ordered[idx])
