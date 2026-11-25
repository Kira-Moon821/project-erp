"""ERP 业务仓储层：产品、客户、订单、库存的读写与分页查询。"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DimCustomer,
    DimDate,
    DimEmployee,
    DimProduct,
    FactInventorySnapshot,
    FactSalesOrder,
    FactSalesOrderItem,
)


def list_products(session: Session, page: int, size: int, category: Optional[str] = None,
                  q: Optional[str] = None, status: Optional[str] = None) -> Tuple[int, List[Dict[str, Any]]]:
    stmt = select(DimProduct)
    count_stmt = select(func.count()).select_from(DimProduct)
    conds = []
    if category:
        conds.append(DimProduct.category == category)
    if status:
        conds.append(DimProduct.status == status)
    if q:
        like = f"%{q}%"
        conds.append((DimProduct.product_name.like(like)) | (DimProduct.sku.like(like)) | (DimProduct.brand.like(like)))
    for cond in conds:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = session.execute(count_stmt).scalar() or 0
    rows = session.execute(stmt.order_by(DimProduct.product_id).offset((page - 1) * size).limit(size)).scalars().all()
    return total, [{"product_id": p.product_id, "sku": p.sku, "product_name": p.product_name,
                    "category": p.category, "brand": p.brand, "unit": p.unit, "unit_cost": p.unit_cost,
                    "list_price": p.list_price, "status": p.status} for p in rows]


def list_customers(session: Session, page: int, size: int, tier: Optional[str] = None,
                   region: Optional[str] = None, q: Optional[str] = None) -> Tuple[int, List[Dict[str, Any]]]:
    stmt = select(DimCustomer, DimEmployee.employee_name).join(
        DimEmployee, DimCustomer.customer_manager_id == DimEmployee.employee_id)
    count_stmt = select(func.count()).select_from(DimCustomer)
    conds = []
    if tier:
        conds.append(DimCustomer.tier == tier)
    if region:
        conds.append(DimCustomer.region == region)
    if q:
        like = f"%{q}%"
        conds.append((DimCustomer.customer_name.like(like)) | (DimCustomer.industry.like(like)) | (DimCustomer.city.like(like)))
    for cond in conds:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = session.execute(count_stmt).scalar() or 0
    rows = session.execute(stmt.order_by(DimCustomer.customer_id).offset((page - 1) * size).limit(size)).all()
    return total, [{"customer_id": c.customer_id, "customer_name": c.customer_name, "industry": c.industry,
                    "region": c.region, "city": c.city, "tier": c.tier, "channel": c.channel,
                    "customer_manager_id": c.customer_manager_id, "customer_manager": mgr,
                    "status": c.status} for c, mgr in rows]


def list_orders(session: Session, page: int, size: int, status: Optional[str] = None,
                customer_id: Optional[int] = None, start: Optional[date] = None,
                end: Optional[date] = None) -> Tuple[int, List[Dict[str, Any]]]:
    stmt = (select(FactSalesOrder, DimCustomer.customer_name)
            .join(DimCustomer, FactSalesOrder.customer_id == DimCustomer.customer_id))
    count_stmt = select(func.count()).select_from(FactSalesOrder)
    conds = []
    if status:
        conds.append(FactSalesOrder.status == status)
    if customer_id:
        conds.append(FactSalesOrder.customer_id == customer_id)
    if start:
        conds.append(FactSalesOrder.order_date_id >= int(start.strftime("%Y%m%d")))
    if end:
        conds.append(FactSalesOrder.order_date_id <= int(end.strftime("%Y%m%d")))
    for cond in conds:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = session.execute(count_stmt).scalar() or 0
    rows = session.execute(stmt.order_by(FactSalesOrder.order_date_id.desc(), FactSalesOrder.order_id.desc())
                           .offset((page - 1) * size).limit(size)).all()
    return total, [{"order_id": o.order_id, "order_no": o.order_no, "customer_id": o.customer_id,
                    "customer_name": name, "net_amount": o.net_amount, "gross_profit": o.gross_profit,
                    "status": o.status, "payment_status": o.payment_status,
                    "order_date_id": o.order_date_id, "channel": o.channel,
                    "delivery_days": o.delivery_days} for o, name in rows]


def get_order_detail(session: Session, order_id: int) -> Optional[Dict[str, Any]]:
    order = session.get(FactSalesOrder, order_id)
    if order is None:
        return None
    customer = session.get(DimCustomer, order.customer_id)
    items = session.execute(
        select(FactSalesOrderItem, DimProduct.sku, DimProduct.product_name, DimProduct.category)
        .join(DimProduct, FactSalesOrderItem.product_id == DimProduct.product_id)
        .where(FactSalesOrderItem.order_id == order_id)
    ).all()
    return {
        "order_id": order.order_id, "order_no": order.order_no,
        "customer": {"customer_id": customer.customer_id, "customer_name": customer.customer_name,
                     "tier": customer.tier, "industry": customer.industry} if customer else None,
        "status": order.status, "payment_status": order.payment_status, "channel": order.channel,
        "order_date_id": order.order_date_id, "delivery_date_id": order.delivery_date_id,
        "gross_amount": order.gross_amount, "discount_amount": order.discount_amount,
        "net_amount": order.net_amount, "cost_amount": order.cost_amount,
        "gross_profit": order.gross_profit, "delivery_days": order.delivery_days,
        "items": [{"product_id": it.product_id, "sku": sku, "product_name": pname, "category": cat,
                   "qty": it.qty, "unit_price": it.unit_price, "discount_rate": it.discount_rate,
                   "revenue_amount": it.revenue_amount} for it, sku, pname, cat in items],
    }


def latest_inventory(session: Session, product_id: Optional[int] = None,
                      warehouse: Optional[str] = None) -> List[Dict[str, Any]]:
    last_date = session.execute(select(func.max(FactInventorySnapshot.date_id))).scalar()
    if last_date is None:
        return []
    stmt = (select(FactInventorySnapshot, DimProduct.sku, DimProduct.product_name, DimProduct.category)
            .join(DimProduct, FactInventorySnapshot.product_id == DimProduct.product_id)
            .where(FactInventorySnapshot.date_id == last_date))
    if product_id:
        stmt = stmt.where(FactInventorySnapshot.product_id == product_id)
    if warehouse:
        stmt = stmt.where(FactInventorySnapshot.warehouse == warehouse)
    rows = session.execute(stmt.order_by(FactInventorySnapshot.inventory_value.desc())).all()
    return [{"product_id": inv.product_id, "sku": sku, "product_name": pname, "category": cat,
             "warehouse": inv.warehouse, "on_hand_qty": inv.on_hand_qty,
             "safety_stock": inv.safety_stock, "stock_gap": inv.on_hand_qty - inv.safety_stock,
             "inventory_value": inv.inventory_value} for inv, sku, pname, cat in rows]


def next_order_id(session: Session) -> int:
    return int(session.execute(select(func.max(FactSalesOrder.order_id))).scalar() or 0) + 1


def today_date_id(session: Session) -> int:
    row = session.execute(select(DimDate.date_id).order_by(DimDate.date_id).limit(1)).scalar()
    return int(row)
