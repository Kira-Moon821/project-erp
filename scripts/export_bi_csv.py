"""导出 BI / Excel 可直接导入的 CSV 事实表（扁平化星型结构）。

产出目录：
    bi/data/*.csv       —— Power BI / Tableau 直接导入
    excel/data/*.csv    —— Excel 数据透视表数据源

编码统一 UTF-8 with BOM（utf-8-sig），Excel 双击打开不乱码。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select                                # noqa: E402

from app.db import models as m                                # noqa: E402
from app.db.session import session_scope                      # noqa: E402


def dump(rows: Iterable[Dict[str, Any]], headers: List[str], target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def main() -> int:
    written: Dict[str, int] = {}
    with session_scope() as s:
        dates = {d.date_id: d for d in s.scalars(select(m.DimDate))}
        employees = {e.employee_id: e for e in s.scalars(select(m.DimEmployee))}
        customers = {c.customer_id: c for c in s.scalars(select(m.DimCustomer))}
        products = {p.product_id: p for p in s.scalars(select(m.DimProduct))}

        # ---------------- 销售订单（销售分析核心事实表） ----------------
        order_rows: List[Dict[str, Any]] = []
        for o in s.scalars(select(m.FactSalesOrder)):
            c = customers[o.customer_id]
            e = employees[o.employee_id]
            d = dates[o.order_date_id]
            order_rows.append({
                "order_id": o.order_id, "order_no": o.order_no,
                "order_date": d.full_date.isoformat(), "year": d.year, "quarter": d.year_quarter,
                "year_month": d.year_month, "month": d.month,
                "customer_id": c.customer_id, "customer_name": c.customer_name,
                "customer_tier": c.tier, "customer_industry": c.industry, "customer_region": c.region,
                "customer_city": c.city, "customer_channel": c.channel,
                "acquisition_source": c.acquisition_source,
                "employee_id": e.employee_id, "employee_name": e.employee_name,
                "sales_team": e.team, "sales_role": e.role,
                "order_channel": o.channel, "order_status": o.status, "payment_status": o.payment_status,
                "gross_amount": o.gross_amount, "discount_amount": o.discount_amount,
                "net_amount": o.net_amount, "cost_amount": o.cost_amount, "gross_profit": o.gross_profit,
                "discount_rate": round(o.discount_amount / o.gross_amount, 4) if o.gross_amount else 0,
                "gross_margin": round(o.gross_profit / o.net_amount, 4) if o.net_amount else 0,
                "delivery_days": o.delivery_days, "is_return": int(o.is_return),
            })
        written["fact_sales_order_flat"] = dump(
            order_rows, list(order_rows[0].keys()), ROOT / "bi" / "data" / "fact_sales_order_flat.csv")

        # ---------------- 订单明细（产品维度分析） ----------------
        order_map = {o.order_id: o for o in s.scalars(select(m.FactSalesOrder))}
        item_rows: List[Dict[str, Any]] = []
        for it in s.scalars(select(m.FactSalesOrderItem)):
            o = order_map[it.order_id]
            p = products[it.product_id]
            d = dates[o.order_date_id]
            c = customers[o.customer_id]
            item_rows.append({
                "order_item_id": it.order_item_id, "order_id": it.order_id, "order_no": o.order_no,
                "order_date": d.full_date.isoformat(), "year": d.year, "year_month": d.year_month,
                "customer_id": c.customer_id, "customer_tier": c.tier, "customer_industry": c.industry,
                "customer_region": c.region, "order_channel": o.channel, "order_status": o.status,
                "product_id": p.product_id, "sku": p.sku, "product_name": p.product_name,
                "category": p.category, "brand": p.brand, "unit": p.unit,
                "qty": it.qty, "unit_price": it.unit_price, "discount_rate": it.discount_rate,
                "revenue_amount": it.revenue_amount, "cost_amount": it.cost_amount,
                "gross_profit": round(it.revenue_amount - it.cost_amount, 2),
            })
        written["fact_sales_order_item_flat"] = dump(
            item_rows, list(item_rows[0].keys()), ROOT / "bi" / "data" / "fact_sales_order_item_flat.csv")

        # ---------------- 库存快照 ----------------
        inv_rows: List[Dict[str, Any]] = []
        for inv in s.scalars(select(m.FactInventorySnapshot)):
            p = products[inv.product_id]
            d = dates[inv.date_id]
            inv_rows.append({
                "snapshot_id": inv.snapshot_id, "snapshot_date": d.full_date.isoformat(),
                "year_month": d.year_month, "year": d.year, "quarter": d.year_quarter,
                "product_id": p.product_id, "sku": p.sku, "product_name": p.product_name,
                "category": p.category, "brand": p.brand,
                "warehouse": inv.warehouse, "on_hand_qty": inv.on_hand_qty,
                "safety_stock": inv.safety_stock, "in_transit_qty": inv.in_transit_qty,
                "stock_gap": inv.on_hand_qty - inv.safety_stock,
                "unit_cost": inv.unit_cost, "inventory_value": inv.inventory_value,
            })
        written["fact_inventory_snapshot_flat"] = dump(
            inv_rows, list(inv_rows[0].keys()), ROOT / "bi" / "data" / "fact_inventory_snapshot_flat.csv")

        # ---------------- 线索与商机（销售漏斗 / AI 辅助） ----------------
        lead_rows: List[Dict[str, Any]] = []
        for lead in s.scalars(select(m.FactLeadOpportunity)):
            d = dates[lead.created_date_id]
            e = employees[lead.owner_employee_id]
            c = customers.get(lead.customer_id)
            lead_rows.append({
                "lead_id": lead.lead_id, "lead_name": lead.lead_name,
                "created_date": d.full_date.isoformat(), "year": d.year, "quarter": d.year_quarter,
                "year_month": d.year_month,
                "customer_id": lead.customer_id, "customer_name": c.customer_name if c else "",
                "customer_tier": c.tier if c else "", "customer_industry": c.industry if c else "",
                "customer_region": c.region if c else "",
                "source_channel": lead.source_channel, "stage": lead.stage,
                "expected_amount": lead.expected_amount, "actual_amount": lead.actual_amount,
                "win_probability": lead.win_probability, "ai_assisted": lead.ai_assisted,
                "cycle_days": lead.cycle_days, "loss_reason": lead.loss_reason or "",
                "owner_employee_id": lead.owner_employee_id, "owner_name": e.employee_name,
                "sales_team": e.team,
            })
        written["fact_lead_opportunity_flat"] = dump(
            lead_rows, list(lead_rows[0].keys()), ROOT / "bi" / "data" / "fact_lead_opportunity_flat.csv")

        # ---------------- 客服工单 ----------------
        ticket_rows: List[Dict[str, Any]] = []
        for t in s.scalars(select(m.FactCustomerTicket)):
            d = dates[t.created_date_id]
            c = customers[t.customer_id]
            ticket_rows.append({
                "ticket_id": t.ticket_id, "created_date": d.full_date.isoformat(),
                "year": d.year, "year_month": d.year_month,
                "customer_id": c.customer_id, "customer_name": c.customer_name,
                "customer_tier": c.tier, "customer_industry": c.industry, "customer_region": c.region,
                "topic_type": t.topic_type, "channel": t.channel, "ai_handled": t.ai_handled,
                "first_response_minutes": t.first_response_minutes, "resolution_hours": t.resolution_hours,
                "satisfaction": t.satisfaction, "converted_to_opportunity": t.converted_to_opportunity,
            })
        written["fact_customer_ticket_flat"] = dump(
            ticket_rows, list(ticket_rows[0].keys()), ROOT / "bi" / "data" / "fact_customer_ticket_flat.csv")

        # ---------------- 营销投放 ----------------
        mkt_rows: List[Dict[str, Any]] = []
        for sp in s.scalars(select(m.FactMarketingSpend)):
            d = dates[sp.date_id]
            mkt_rows.append({
                "spend_id": sp.spend_id, "date": d.full_date.isoformat(), "year": d.year,
                "year_month": d.year_month, "channel": sp.channel, "campaign_name": sp.campaign_name,
                "cost_amount": sp.cost_amount, "leads_count": sp.leads_count,
                "revenue_attributed": sp.revenue_attributed,
                "cac": round(sp.cost_amount / sp.leads_count, 2) if sp.leads_count else 0,
                "roas": round(sp.revenue_attributed / sp.cost_amount, 2) if sp.cost_amount else 0,
            })
        written["fact_marketing_spend_flat"] = dump(
            mkt_rows, list(mkt_rows[0].keys()), ROOT / "bi" / "data" / "fact_marketing_spend_flat.csv")

        # ---------------- AI 使用记录 ----------------
        ai_rows: List[Dict[str, Any]] = []
        for u in s.scalars(select(m.FactAiUsage)):
            d = dates[u.date_id]
            e = employees[u.employee_id]
            ai_rows.append({
                "usage_id": u.usage_id, "date": d.full_date.isoformat(), "year": d.year,
                "year_month": d.year_month, "employee_id": e.employee_id, "employee_name": e.employee_name,
                "sales_team": e.team, "sales_role": e.role,
                "scenario": u.scenario, "query_count": u.query_count,
                "accepted_count": u.accepted_count,
                "acceptance_rate": round(u.accepted_count / u.query_count, 4) if u.query_count else 0,
                "minutes_saved": u.minutes_saved,
            })
        written["fact_ai_usage_flat"] = dump(
            ai_rows, list(ai_rows[0].keys()), ROOT / "bi" / "data" / "fact_ai_usage_flat.csv")

        # ---------------- 维度表 ----------------
        dim_rows = {
            "dim_date": [{
                "date_id": d.date_id, "full_date": d.full_date.isoformat(), "year": d.year,
                "quarter": d.year_quarter, "year_month": d.year_month, "month": d.month,
                "month_name": d.month_name, "week_of_year": d.week_of_year,
                "day_of_week": d.day_of_week, "is_weekend": int(d.is_weekend),
            } for d in dates.values()],
            "dim_employee": [{
                "employee_id": e.employee_id, "employee_name": e.employee_name, "team": e.team,
                "role": e.role, "region": e.region, "hire_date": e.hire_date.isoformat(),
                "is_active": int(e.is_active),
            } for e in employees.values()],
            "dim_customer": [{
                "customer_id": c.customer_id, "customer_name": c.customer_name, "industry": c.industry,
                "region": c.region, "city": c.city, "tier": c.tier, "channel": c.channel,
                "acquisition_source": c.acquisition_source, "contract_date": c.contract_date.isoformat(),
                "customer_manager_id": c.customer_manager_id, "customer_manager": employees[c.customer_manager_id].employee_name,
                "annual_contract_value": c.annual_contract_value, "status": c.status,
            } for c in customers.values()],
            "dim_product": [{
                "product_id": p.product_id, "sku": p.sku, "product_name": p.product_name,
                "category": p.category, "brand": p.brand, "unit": p.unit,
                "unit_cost": p.unit_cost, "list_price": p.list_price, "supplier_id": p.supplier_id,
                "launch_date": p.launch_date.isoformat(), "status": p.status,
            } for p in products.values()],
        }
        for name, rows in dim_rows.items():
            written[name] = dump(rows, list(rows[0].keys()), ROOT / "bi" / "data" / f"{name}.csv")

    # Excel 数据源副本（同一份数据，便于做透视表）
    for csv_path in (ROOT / "bi" / "data").glob("*.csv"):
        target = ROOT / "excel" / "data" / csv_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(csv_path.read_bytes())

    for name, count in written.items():
        print(f"{name:34s} {count:>8d} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
