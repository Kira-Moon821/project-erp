"""ORM 数据模型（SQLAlchemy 2.0 声明式）。

同一套模型同时服务 SQLite 与 MySQL 8：DDL 由 scripts/export_schema.py 按两种方言导出，
保证「数据库脚本 / 后端代码 / BI 事实表」三者口径一致。

维度表：dim_date / dim_employee / dim_supplier / dim_product / dim_customer
事实表：fact_sales_order / fact_sales_order_item / fact_purchase_order
        fact_inventory_snapshot / fact_inventory_transaction
        fact_lead_opportunity / fact_customer_ticket / fact_marketing_spend / fact_ai_usage
系统表：sys_user / sys_refresh_token
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- 维度表
class DimDate(Base):
    __tablename__ = "dim_date"

    date_id: Mapped[int] = mapped_column(Integer, primary_key=True)          # YYYYMMDD
    full_date: Mapped[date] = mapped_column(Date, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    month_name: Mapped[str] = mapped_column(String(16), nullable=False)
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)        # 2024-07
    year_quarter: Mapped[str] = mapped_column(String(6), nullable=False)      # 2024Q3
    week_of_year: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)          # 1=周一
    is_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DimEmployee(Base):
    __tablename__ = "dim_employee"

    employee_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_name: Mapped[str] = mapped_column(String(32), nullable=False)
    team: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    region: Mapped[str] = mapped_column(String(16), nullable=False)
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class DimSupplier(Base):
    __tablename__ = "dim_supplier"

    supplier_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_name: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(16), nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[float] = mapped_column(Float, nullable=False)


class DimProduct(Base):
    __tablename__ = "dim_product"

    product_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    product_name: Mapped[str] = mapped_column(String(96), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    brand: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str] = mapped_column(String(8), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    list_price: Mapped[float] = mapped_column(Float, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("dim_supplier.supplier_id"), nullable=False)
    launch_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="在售")


class DimCustomer(Base):
    __tablename__ = "dim_customer"

    customer_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(96), nullable=False)
    industry: Mapped[str] = mapped_column(String(32), nullable=False)
    region: Mapped[str] = mapped_column(String(16), nullable=False)
    city: Mapped[str] = mapped_column(String(32), nullable=False)
    tier: Mapped[str] = mapped_column(String(4), nullable=False)              # A/B/C
    channel: Mapped[str] = mapped_column(String(16), nullable=False)         # 直销/经销/电商/OEM
    acquisition_source: Mapped[str] = mapped_column(String(16), nullable=False)
    contract_date: Mapped[date] = mapped_column(Date, nullable=False)
    customer_manager_id: Mapped[int] = mapped_column(ForeignKey("dim_employee.employee_id"), nullable=False)
    annual_contract_value: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="合作中")


# --------------------------------------------------------------------------- 销售事实
class FactSalesOrder(Base):
    __tablename__ = "fact_sales_order"
    __table_args__ = (
        Index("ix_fso_date", "order_date_id"),
        Index("ix_fso_customer", "customer_id"),
        Index("ix_fso_employee", "employee_id"),
    )

    order_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("dim_customer.customer_id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("dim_employee.employee_id"), nullable=False)
    order_date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=False)
    delivery_date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)            # 已完成/已退款/处理中/已取消
    payment_status: Mapped[str] = mapped_column(String(16), nullable=False)   # 已付/部分付款/未付款
    gross_amount: Mapped[float] = mapped_column(Float, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, nullable=False)
    net_amount: Mapped[float] = mapped_column(Float, nullable=False)
    cost_amount: Mapped[float] = mapped_column(Float, nullable=False)
    gross_profit: Mapped[float] = mapped_column(Float, nullable=False)
    delivery_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_return: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class FactSalesOrderItem(Base):
    __tablename__ = "fact_sales_order_item"
    __table_args__ = (
        Index("ix_fsoi_order", "order_id"),
        Index("ix_fsoi_product", "product_id"),
    )

    order_item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("fact_sales_order.order_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("dim_product.product_id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    discount_rate: Mapped[float] = mapped_column(Float, nullable=False)
    revenue_amount: Mapped[float] = mapped_column(Float, nullable=False)
    cost_amount: Mapped[float] = mapped_column(Float, nullable=False)


class FactPurchaseOrder(Base):
    __tablename__ = "fact_purchase_order"

    purchase_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("dim_supplier.supplier_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("dim_product.product_id"), nullable=False)
    order_date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=False)
    arrival_date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)            # 在途/已入库/已取消


# --------------------------------------------------------------------------- 库存事实
class FactInventorySnapshot(Base):
    __tablename__ = "fact_inventory_snapshot"
    __table_args__ = (Index("ix_fis_date_product", "date_id", "product_id"),)

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("dim_product.product_id"), nullable=False)
    warehouse: Mapped[str] = mapped_column(String(16), nullable=False)
    on_hand_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False)
    in_transit_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    inventory_value: Mapped[float] = mapped_column(Float, nullable=False)


class FactInventoryTransaction(Base):
    __tablename__ = "fact_inventory_transaction"
    __table_args__ = (Index("ix_fit_date", "date_id"), Index("ix_fit_product", "product_id"))

    txn_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("dim_product.product_id"), nullable=False)
    warehouse: Mapped[str] = mapped_column(String(16), nullable=False)
    txn_type: Mapped[str] = mapped_column(String(16), nullable=False)   # 采购入库/销售出库/退货入库/报废
    qty: Mapped[int] = mapped_column(Integer, nullable=False)          # 正数入库 / 负数出库
    ref_no: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)


# --------------------------------------------------------------------------- 销售过程事实（AI 产品销售思考的数据底座）
class FactLeadOpportunity(Base):
    """线索 → 商机 → 成单漏斗；ai_assisted 标记该商机是否被 AI 助手辅助。"""

    __tablename__ = "fact_lead_opportunity"
    __table_args__ = (Index("ix_flo_created", "created_date_id"), Index("ix_flo_stage", "stage"))

    lead_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_name: Mapped[str] = mapped_column(String(96), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("dim_customer.customer_id"), nullable=True)
    source_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    created_date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=False)
    close_date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=True)
    owner_employee_id: Mapped[int] = mapped_column(ForeignKey("dim_employee.employee_id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)   # 线索/需求确认/方案演示/商务谈判/成单/输单
    expected_amount: Mapped[float] = mapped_column(Float, nullable=False)
    actual_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    win_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    ai_assisted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)   # 0/1
    cycle_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    loss_reason: Mapped[str] = mapped_column(String(64), nullable=True)


class FactCustomerTicket(Base):
    """售前/售后工单：用于衡量响应效率与 AI 辅助后的改善。"""

    __tablename__ = "fact_customer_ticket"
    __table_args__ = (Index("ix_fct_created", "created_date_id"),)

    ticket_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("dim_customer.customer_id"), nullable=False)
    created_date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=False)
    topic_type: Mapped[str] = mapped_column(String(24), nullable=False)   # 数据导出/报表需求/系统故障/功能咨询/售后
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    ai_handled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_response_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_hours: Mapped[float] = mapped_column(Float, nullable=False)
    satisfaction: Mapped[int] = mapped_column(Integer, nullable=False)
    converted_to_opportunity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class FactMarketingSpend(Base):
    __tablename__ = "fact_marketing_spend"

    spend_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    campaign_name: Mapped[str] = mapped_column(String(48), nullable=False)
    cost_amount: Mapped[float] = mapped_column(Float, nullable=False)
    leads_count: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue_attributed: Mapped[float] = mapped_column(Float, nullable=False)


class FactAiUsage(Base):
    """企业内部 AI 助手使用记录：支撑「AI 采纳率 / 节省工时」这类 ROI 口径。"""

    __tablename__ = "fact_ai_usage"
    __table_args__ = (Index("ix_fau_date", "date_id"),)

    usage_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date_id: Mapped[int] = mapped_column(ForeignKey("dim_date.date_id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("dim_employee.employee_id"), nullable=False)
    scenario: Mapped[str] = mapped_column(String(32), nullable=False)
    query_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    minutes_saved: Mapped[float] = mapped_column(Float, nullable=False)


# --------------------------------------------------------------------------- 系统表
class SysUser(Base):
    __tablename__ = "sys_user"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(160), nullable=False)
    full_name: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)      # admin/sales/analyst/viewer
    employee_id: Mapped[int] = mapped_column(ForeignKey("dim_employee.employee_id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class SysRefreshToken(Base):
    __tablename__ = "sys_refresh_token"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.user_id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


ALL_MODELS = [
    DimDate, DimEmployee, DimSupplier, DimProduct, DimCustomer,
    FactSalesOrder, FactSalesOrderItem, FactPurchaseOrder,
    FactInventorySnapshot, FactInventoryTransaction,
    FactLeadOpportunity, FactCustomerTicket, FactMarketingSpend, FactAiUsage,
    SysUser, SysRefreshToken,
]
