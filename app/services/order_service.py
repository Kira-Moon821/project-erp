"""订单服务：创建订单的事务边界与业务规则校验。

多步写入（订单主表 + 明细 + 库存出库流水）必须整体成功或整体回滚。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.db.models import (
    DimCustomer,
    DimDate,
    DimProduct,
    FactInventorySnapshot,
    FactInventoryTransaction,
    FactSalesOrder,
    FactSalesOrderItem,
)
from app.repositories import erp_repo
from app.schemas.models import SalesOrderIn

WAREHOUSE_BY_REGION = {"华东": "华东仓", "华南": "华东仓", "华北": "华东仓", "西南": "西南仓"}


def create_order(session: Session, payload: SalesOrderIn) -> Dict[str, Any]:
    customer = session.get(DimCustomer, payload.customer_id)
    if customer is None:
        raise NotFoundError(f"客户不存在：{payload.customer_id}")
    if customer.status != "合作中":
        raise BusinessRuleError(f"客户「{customer.customer_name}」状态为 {customer.status}，不可下单")

    date_id = session.execute(select(func.max(DimDate.date_id))).scalar()
    if date_id is None:
        raise BusinessRuleError("日期维度表为空，无法创建订单")

    # 明细与金额计算
    items: List[Dict[str, Any]] = []
    gross = discount = cost = 0.0
    for line in payload.items:
        product = session.get(DimProduct, line.product_id)
        if product is None:
            raise NotFoundError(f"商品不存在：{line.product_id}")
        if product.status != "在售":
            raise BusinessRuleError(f"商品「{product.product_name}」已停产，不可下单")
        line_gross = round(line.qty * product.list_price, 2)
        line_revenue = round(line_gross * (1 - line.discount_rate), 2)
        line_cost = round(line.qty * product.unit_cost, 2)
        gross += line_gross
        discount += line_gross - line_revenue
        cost += line_cost
        items.append({"product": product, "qty": line.qty, "unit_price": product.list_price,
                      "discount_rate": line.discount_rate, "revenue_amount": line_revenue,
                      "cost_amount": line_cost})

    gross, discount, cost = round(gross, 2), round(discount, 2), round(cost, 2)
    net = round(gross - discount, 2)

    # 库存校验：按客户所在区域的仓库扣减，可用库存不足直接拦截
    warehouse = WAREHOUSE_BY_REGION.get(customer.region, "华东仓")
    last_date = session.execute(select(func.max(FactInventorySnapshot.date_id))).scalar()
    shortages: List[Dict[str, Any]] = []
    for item in items:
        available = session.execute(
            select(func.coalesce(func.sum(FactInventorySnapshot.on_hand_qty), 0))
            .where(FactInventorySnapshot.date_id == last_date,
                   FactInventorySnapshot.product_id == item["product"].product_id,
                   FactInventorySnapshot.warehouse == warehouse)
        ).scalar()
        if int(available) < item["qty"]:
            shortages.append({"product_id": item["product"].product_id,
                              "product_name": item["product"].product_name,
                              "requested": item["qty"], "available": int(available),
                              "warehouse": warehouse})
    if shortages:
        raise BusinessRuleError("库存不足，订单未创建", {"shortages": shortages})

    # 写入：订单主表 + 明细 + 出库流水
    order_id = erp_repo.next_order_id(session)
    order_no = f"SO{str(date_id)[:6]}{order_id:05d}"
    order = FactSalesOrder(
        order_id=order_id, order_no=order_no, customer_id=customer.customer_id,
        employee_id=payload.employee_id or customer.customer_manager_id,
        order_date_id=int(date_id), delivery_date_id=int(date_id),
        channel=payload.channel or customer.channel, status="处理中", payment_status="未付款",
        gross_amount=gross, discount_amount=discount, net_amount=net, cost_amount=cost,
        gross_profit=round(net - cost, 2), delivery_days=0, is_return=False,
    )
    session.add(order)

    for index, item in enumerate(items, start=1):
        session.add(FactSalesOrderItem(
            order_item_id=int(session.execute(select(func.coalesce(func.max(FactSalesOrderItem.order_item_id), 0))).scalar() or 0) + index,
            order_id=order_id, product_id=item["product"].product_id, qty=item["qty"],
            unit_price=item["unit_price"], discount_rate=item["discount_rate"],
            revenue_amount=item["revenue_amount"], cost_amount=item["cost_amount"],
        ))
        session.add(FactInventoryTransaction(
            txn_id=int(session.execute(select(func.coalesce(func.max(FactInventoryTransaction.txn_id), 0))).scalar() or 0) + index,
            date_id=int(date_id), product_id=item["product"].product_id, warehouse=warehouse,
            txn_type="销售出库", qty=-item["qty"], ref_no=order_no,
            unit_cost=item["product"].unit_cost,
        ))

    session.flush()
    return {"order_id": order_id, "order_no": order_no, "customer_id": customer.customer_id,
            "net_amount": net, "gross_profit": round(net - cost, 2), "status": "处理中"}
