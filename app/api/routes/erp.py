"""ERP 业务路由：产品、客户、订单、库存。"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import pagination, require_permission
from app.core.errors import NotFoundError
from app.db.models import SysUser
from app.db.session import get_db
from app.repositories import erp_repo
from app.schemas.models import Paginated, SalesOrderIn, SalesOrderOut
from app.services import order_service

router = APIRouter(tags=["ERP 业务"])


@router.get("/products", response_model=Paginated, summary="产品列表（分页/筛选）")
def products(page: int = 1, size: int = 20, category: Optional[str] = None,
             q: Optional[str] = None, status: Optional[str] = None,
             session: Session = Depends(get_db),
             _user: SysUser = Depends(require_permission("read"))) -> Paginated:
    p, s = pagination(page, size)
    total, items = erp_repo.list_products(session, p, s, category=category, q=q, status=status)
    return Paginated(total=total, page=p, size=s, items=items)


@router.get("/customers", response_model=Paginated, summary="客户列表（分页/筛选）")
def customers(page: int = 1, size: int = 20, tier: Optional[str] = None,
              region: Optional[str] = None, q: Optional[str] = None,
              session: Session = Depends(get_db),
              _user: SysUser = Depends(require_permission("read"))) -> Paginated:
    p, s = pagination(page, size)
    total, items = erp_repo.list_customers(session, p, s, tier=tier, region=region, q=q)
    return Paginated(total=total, page=p, size=s, items=items)


@router.get("/sales-orders", response_model=Paginated, summary="订单列表（分页/筛选）")
def sales_orders(page: int = 1, size: int = 20, status: Optional[str] = None,
                 customer_id: Optional[int] = None, start: Optional[str] = None, end: Optional[str] = None,
                 session: Session = Depends(get_db),
                 _user: SysUser = Depends(require_permission("read"))) -> Paginated:
    p, s = pagination(page, size)
    sd = date.fromisoformat(start) if start else None
    ed = date.fromisoformat(end) if end else None
    total, items = erp_repo.list_orders(session, p, s, status=status, customer_id=customer_id, start=sd, end=ed)
    return Paginated(total=total, page=p, size=s, items=items)


@router.get("/sales-orders/{order_id}", summary="订单详情（含明细）")
def sales_order_detail(order_id: int, session: Session = Depends(get_db),
                        _user: SysUser = Depends(require_permission("read"))) -> Dict[str, Any]:
    detail = erp_repo.get_order_detail(session, order_id)
    if detail is None:
        raise NotFoundError(f"订单不存在：{order_id}")
    return detail


@router.post("/sales-orders", response_model=SalesOrderOut, status_code=201, summary="创建订单（校验库存并写流水）")
def create_sales_order(payload: SalesOrderIn, session: Session = Depends(get_db),
                       _user: SysUser = Depends(require_permission("write"))) -> SalesOrderOut:
    result = order_service.create_order(session, payload)
    session.commit()
    return SalesOrderOut(**result)


@router.get("/inventory", summary="最新库存快照")
def inventory(product_id: Optional[int] = None, warehouse: Optional[str] = None,
              session: Session = Depends(get_db),
              _user: SysUser = Depends(require_permission("read"))) -> List[Dict[str, Any]]:
    return erp_repo.latest_inventory(session, product_id=product_id, warehouse=warehouse)
