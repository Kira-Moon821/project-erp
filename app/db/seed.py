"""确定性种子数据生成器。

设计原则（口径见 docs/数据字典与业务口径.md）：
1. 24 个月连续经营数据（2024-01-01 ~ 2025-12-31），确定性随机（seed=42），任何机器跑出来完全一致；
2. 数据里内置了**可被分析验证的业务规律**，而不是纯噪声：
   - 季节性：Q4 旺（×1.35）、Q1 淡（×0.85）、2 月春节淡（×0.70）
   - 年度增长：2025 相对 2024 约 +15%~18%
   - 客户分层影响客单价与折扣：A 类客单高、折扣深；C 类走量
   - AI 辅助线索赢率更高、销售周期更短、成单率更高（支撑「AI 产品价值」论证）
   - AI 处理工单首次响应更快、满意度更高
3. 库存严格可对账：所有出入库（含期初建账）都落在 fact_inventory_transaction，
   月末快照 = 截至该日全部流水累加，满足「期初 + 入库 − 出库 = 期末」。
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy import case, delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.db import models as m

# --------------------------------------------------------------------------- 静态语料
INDUSTRIES = ["智能制造", "汽车零部件", "医疗器械", "电子代工", "新能源", "食品饮料", "化工", "物流仓储"]
REGIONS = ["华东", "华南", "西南", "华北"]
CITIES = {
    "华东": ["上海", "苏州", "杭州", "宁波", "无锡"],
    "华南": ["深圳", "广州", "东莞", "佛山"],
    "西南": ["成都", "重庆", "昆明", "贵阳"],
    "华北": ["北京", "天津", "石家庄", "青岛"],
}
CHANNELS = ["直销", "经销", "电商", "OEM"]
ACQUISITION = ["官网", "展会", "转介绍", "广告投放", "电话外呼", "内容营销"]
TIERS = ["A", "B", "C"]
SUPPLIER_NAMES = ["恒达精密", "中启自动化", "锐川机电", "华宇传动", "博联电气", "天工液压", "晟远科技", "瑞驰轴承", "普林气动", "凯盛电子"]
CATEGORY_SPEC = [
    ("工业传感器", "件", 320.0, 480.0, ["汉威", "基恩士", "西克"]),
    ("伺服电机", "台", 1800.0, 2650.0, ["汇川", "安川", "松下"]),
    ("PLC控制器", "台", 2400.0, 3500.0, ["西门子", "三菱", "欧姆龙"]),
    ("精密减速机", "台", 3200.0, 4600.0, ["哈默纳科", "绿的谐波"]),
    ("变频器", "台", 1500.0, 2250.0, ["英威腾", "施耐德"]),
    ("气动元件", "套", 260.0, 390.0, ["SMC", "亚德客"]),
    ("工业交换机", "台", 900.0, 1350.0, ["研华", "菲尼玛"]),
    ("电源模块", "个", 380.0, 560.0, ["明纬", "欧陆科"]),
]
PRODUCT_WORDS = ["标准型", "增强型", "紧凑型", "高防护型", "高精度型", "经济型", "定制型", "防爆型"]
EMPLOYEE_NAMES = [
    "陈思远", "林可欣", "王浩然", "赵梦琪", "刘泽宇", "孙雅静", "周天成", "吴悦琳", "郑昊然", "冯佳怡",
    "黄俊驰", "徐若彤", "马晨曦", "高雪莉", "何立诚", "罗子谦", "梁婉清", "谢文博",
]
TEAMS = ["华东销售组", "华南销售组", "西南销售组", "大客户组", "线上运营组"]
ROLES = ["销售顾问"] * 7 + ["高级销售顾问"] * 4 + ["销售主管"] * 3 + ["售前顾问"] * 2 + ["销售运营"] * 1 + ["销售总监"] * 1
COMPANY_PREFIX = ["苏州", "上海", "深圳", "广州", "成都", "重庆", "杭州", "宁波", "无锡", "东莞", "武汉", "青岛", "天津", "西安", "合肥"]
COMPANY_SUFFIX = ["智能装备", "精密制造", "自动化科技", "电子科技", "医疗器械", "新能源材料", "食品机械", "化工装备", "物流科技", "汽车零部件"]
LEAD_TOPICS = ["生产线数据看板", "设备预测性维护", "库存与采购优化", "质量追溯系统", "能耗分析平台", "销售漏斗管理", "财务对账自动化", "MES 数据打通"]
TICKET_TOPICS = ["数据导出", "报表需求", "系统故障", "功能咨询", "售后支持"]
AI_SCENARIOS = ["自然语言取数", "经营日报生成", "客户洞察摘要"]
WAREHOUSES = ["华东仓", "西南仓"]
OPENING_REF = "OPENING-2024"


def _seasonality(d: date) -> float:
    """月份季节因子：Q4 旺、Q1 淡、2 月春节淡。"""
    return {1: 0.85, 2: 0.70, 3: 0.95, 4: 1.00, 5: 1.05, 6: 1.08, 7: 0.95, 8: 0.92,
            9: 1.10, 10: 1.15, 11: 1.25, 12: 1.35}[d.month]


def _growth(d: date, start: date) -> float:
    """年度增长：每月约 +1.4%，复合约 +18%/年。"""
    months = (d.year - start.year) * 12 + (d.month - start.month)
    return 1.0 + 0.014 * months


def build_dim_date(start: date, end: date) -> List[Dict[str, Any]]:
    """维度表额外覆盖业务窗口之后的 90 天，用于承载交付日期等尾部日期。"""
    rows, cur = [], start
    tail = end + timedelta(days=90)
    while cur <= tail:
        iso = cur.isocalendar()
        rows.append({
            "date_id": int(cur.strftime("%Y%m%d")),
            "full_date": cur,
            "year": cur.year,
            "quarter": (cur.month - 1) // 3 + 1,
            "month": cur.month,
            "month_name": f"{cur.month}月",
            "year_month": cur.strftime("%Y-%m"),
            "year_quarter": f"{cur.year}Q{(cur.month - 1) // 3 + 1}",
            "week_of_year": iso[1],
            "day_of_week": cur.weekday() + 1,
            "is_weekend": cur.weekday() >= 5,
        })
        cur += timedelta(days=1)
    return rows


def build_suppliers(rng: random.Random) -> List[Dict[str, Any]]:
    return [{
        "supplier_id": i,
        "supplier_name": name,
        "region": rng.choice(REGIONS),
        "lead_time_days": rng.randint(5, 30),
        "rating": round(rng.uniform(3.2, 5.0), 1),
    } for i, name in enumerate(SUPPLIER_NAMES, start=1)]


def build_employees(rng: random.Random, start: date) -> List[Dict[str, Any]]:
    rows = []
    for i, name in enumerate(EMPLOYEE_NAMES, start=1):
        team = TEAMS[min(i - 1, len(TEAMS) - 1)]
        rows.append({
            "employee_id": i,
            "employee_name": name,
            "team": team,
            "role": ROLES[i - 1],
            "region": "华东" if ("华东" in team or "线上" in team) else
                      ("华南" if "华南" in team else ("西南" if "西南" in team else "全国")),
            "hire_date": start - timedelta(days=rng.randint(120, 1500)),
            "is_active": True,
        })
    return rows


def build_products(rng: random.Random, suppliers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows, pid = [], 0
    for category, unit, low, high, brands in CATEGORY_SPEC:
        for _ in range(10):
            pid += 1
            brand = rng.choice(brands)
            unit_cost = round(rng.uniform(low * 0.55, low * 0.85), 2)
            list_price = round(unit_cost * rng.uniform(1.35, 1.75), 2)
            rows.append({
                "product_id": pid,
                "sku": f"SKU-{pid:04d}",
                "product_name": f"{brand} {rng.choice(PRODUCT_WORDS)}{category}",
                "category": category,
                "brand": brand,
                "unit": unit,
                "unit_cost": unit_cost,
                "list_price": list_price,
                "supplier_id": rng.choice(suppliers)["supplier_id"],
                "launch_date": date(2023, 1, 1) + timedelta(days=rng.randint(0, 700)),
                "status": "停产" if rng.random() < 0.05 else "在售",
            })
    return rows


def build_customers(rng: random.Random, employees: List[Dict[str, Any]], start: date) -> List[Dict[str, Any]]:
    sales = [e for e in employees if e["role"] in {"销售顾问", "高级销售顾问", "销售主管", "销售总监"}]
    rows, used = [], set()
    for i in range(1, 61):
        while True:
            name = f"{rng.choice(COMPANY_PREFIX)}{rng.choice(COMPANY_SUFFIX)}有限公司"
            if name not in used:
                used.add(name)
                break
        tier = "A" if i <= 10 else ("B" if i <= 30 else "C")
        region = rng.choice(REGIONS)
        rows.append({
            "customer_id": i,
            "customer_name": name,
            "industry": rng.choice(INDUSTRIES),
            "region": region,
            "city": rng.choice(CITIES[region]),
            "tier": tier,
            "channel": rng.choices(CHANNELS, weights=[45, 30, 15, 10])[0],
            "acquisition_source": rng.choices(ACQUISITION, weights=[25, 20, 22, 15, 10, 8])[0],
            "contract_date": start - timedelta(days=rng.randint(30, 1200)),
            "customer_manager_id": rng.choice(sales)["employee_id"],
            "annual_contract_value": round({"A": rng.uniform(800, 3000), "B": rng.uniform(200, 800),
                                            "C": rng.uniform(20, 200)}[tier] * 1000, 2),
            "status": "合作中" if rng.random() > 0.06 else "已流失",
        })
    return rows


def _warehouse_of(customer: Dict[str, Any]) -> str:
    """华东/华南/华北客户走华东仓，西南客户走西南仓。"""
    return "华东仓" if customer["region"] in {"华东", "华南", "华北"} else "西南仓"


def build_orders(
    rng: random.Random,
    dates: List[Dict[str, Any]],
    customers: List[Dict[str, Any]],
    products: List[Dict[str, Any]],
    start: date,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Dict[str, Dict[int, int]]]]:
    """生成订单与明细，并统计每月各仓库各商品需求量（供采购补货使用）。"""
    orders: List[Dict[str, Any]] = []
    items: List[Dict[str, Any]] = []
    # demand[year_month][warehouse][product_id] = 需求量
    demand: Dict[str, Dict[str, Dict[int, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    tier_weight = {"A": 10, "B": 4, "C": 2}
    tier_discount = {"A": 0.12, "B": 0.07, "C": 0.03}
    tier_price_factor = {"A": 1.0, "B": 0.72, "C": 0.45}
    active_products = [p for p in products if p["status"] == "在售"]
    product_cost = {p["product_id"]: p["unit_cost"] for p in products}

    order_id = 0
    item_id = 0
    for drow in dates:
        d = drow["full_date"]
        expected = 7 * _seasonality(d) * _growth(d, start)
        n_orders = max(0, int(rng.gauss(expected, expected * 0.28)))
        for _ in range(n_orders):
            order_id += 1
            customer = rng.choices(customers, weights=[tier_weight[c["tier"]] for c in customers])[0]
            warehouse = _warehouse_of(customer)
            employee_id = customer["customer_manager_id"] if rng.random() < 0.8 else rng.randint(1, 18)
            order_date_id = drow["date_id"]
            delivery_days = max(1, int(rng.gauss(9 if customer["region"] == "华东" else 14, 4)))
            delivery_date_id = int((d + timedelta(days=delivery_days)).strftime("%Y%m%d"))

            chosen = rng.sample(active_products, rng.choices([1, 2, 3, 4, 5, 6], weights=[26, 27, 20, 14, 8, 5])[0])
            gross = discount_total = cost_total = 0.0
            order_items = []
            for p in chosen:
                qty = rng.choices([1, 2, 3, 5, 8, 10, 20, 50], weights=[20, 20, 15, 14, 12, 8, 7, 4])[0]
                if p["category"] in {"PLC控制器", "精密减速机"}:
                    qty = max(1, qty // 5)
                unit_price = max(
                    round(p["unit_cost"] * 1.08, 2),
                    round(p["list_price"] * tier_price_factor[customer["tier"]] * rng.uniform(0.94, 1.04), 2),
                )
                disc_rate = min(0.35, max(0.0, rng.gauss(tier_discount[customer["tier"]], 0.03)))
                revenue = round(qty * unit_price * (1 - disc_rate), 2)
                cost = round(qty * p["unit_cost"], 2)
                gross += qty * unit_price
                discount_total += qty * unit_price - revenue
                cost_total += cost
                item_id += 1
                order_items.append({
                    "order_item_id": item_id, "order_id": order_id, "product_id": p["product_id"],
                    "qty": qty, "unit_price": unit_price, "discount_rate": round(disc_rate, 4),
                    "revenue_amount": revenue, "cost_amount": cost,
                })
                demand[drow["year_month"]][warehouse][p["product_id"]] += qty

            gross, discount_total = round(gross, 2), round(discount_total, 2)
            net = round(gross - discount_total, 2)
            cost_total = round(cost_total, 2)

            r = rng.random()
            status = "已完成" if r < 0.95 else ("已退款" if r < 0.965 else ("处理中" if r < 0.982 else "已取消"))
            is_return = status == "已退款"
            if status == "已完成":
                pay = rng.choices(["已付", "部分付款", "未付款"], weights=[82, 12, 6])[0]
            elif status == "处理中":
                pay = "未付款"
            else:
                pay = "已付" if is_return else "未付款"

            order_no = f"SO{d.strftime('%Y%m%d')}{order_id:05d}"
            orders.append({
                "order_id": order_id, "order_no": order_no,
                "customer_id": customer["customer_id"], "employee_id": employee_id,
                "order_date_id": order_date_id, "delivery_date_id": delivery_date_id,
                "channel": customer["channel"], "status": status, "payment_status": pay,
                "gross_amount": gross, "discount_amount": discount_total, "net_amount": net,
                "cost_amount": cost_total, "gross_profit": round(net - cost_total, 2),
                "delivery_days": delivery_days, "is_return": is_return,
            })
            items.extend(order_items)
    return orders, items, demand


def build_purchases(
    rng: random.Random,
    dates: List[Dict[str, Any]],
    demand: Dict[str, Dict[str, Dict[int, int]]],
    products: List[Dict[str, Any]],
    end: date,
) -> Tuple[List[Dict[str, Any]], Dict[int, str]]:
    """按「月 × 仓库 × 商品」精确补货：采购量 ≈ 当月该仓库该商品需求的 1.05~1.25 倍。

    返回 (采购单列表, 采购单ID → 入库仓库)。入库仓库必须与销售出库仓库一致，
    否则单仓库存会失衡，月末快照无法与流水对账。
    """
    product_by_id = {p["product_id"]: p for p in products}
    purchases: List[Dict[str, Any]] = []
    po_warehouse: Dict[int, str] = {}
    seq = 0
    for drow in dates:
        ym = drow["year_month"]
        if drow["full_date"].day != 5:
            continue
        for warehouse, product_demand in demand.get(ym, {}).items():
            for pid, need in product_demand.items():
                if need <= 0:
                    continue
                seq += 1
                p = product_by_id[pid]
                qty = max(10, int(need * rng.uniform(0.88, 1.00)))
                lead = rng.randint(5, 30)
                arrival = drow["full_date"] + timedelta(days=lead)
                purchase_no = f"PO{drow['full_date'].strftime('%Y%m%d')}{seq:05d}"
                purchases.append({
                    "purchase_id": seq, "purchase_no": purchase_no, "supplier_id": p["supplier_id"],
                    "product_id": pid, "order_date_id": drow["date_id"],
                    "arrival_date_id": int(arrival.strftime("%Y%m%d")),
                    "qty": qty, "total_amount": round(qty * p["unit_cost"], 2),
                    "status": "在途" if arrival > end else "已入库",
                })
                po_warehouse[seq] = warehouse
    return purchases, po_warehouse


def build_transactions(
    rng: random.Random,
    orders: List[Dict[str, Any]],
    items: List[Dict[str, Any]],
    purchases: List[Dict[str, Any]],
    po_warehouse: Dict[int, str],
    demand: Dict[str, Dict[str, Dict[int, int]]],
    products: List[Dict[str, Any]],
    customers: Dict[int, Dict[str, Any]],
    end: date,
) -> List[Dict[str, Any]]:
    """库存流水：期初建账 + 销售出库 + 采购入库 + 退货入库 + 报废。"""
    product_cost = {p["product_id"]: p["unit_cost"] for p in products}
    order_map = {o["order_id"]: o for o in orders}
    txns: List[Dict[str, Any]] = []
    txn_id = 0

    # 期初建账：按「仓库 × 商品」的峰值月需求给 1.6 个月备货，保证起始库存为正且全程不为负
    peak_demand: Dict[Tuple[str, int], int] = defaultdict(int)
    for ym, wh_map in demand.items():
        for warehouse, product_map in wh_map.items():
            for pid, qty in product_map.items():
                peak_demand[(warehouse, pid)] = max(peak_demand[(warehouse, pid)], qty)
    for (warehouse, pid), peak in peak_demand.items():
        txn_id += 1
        txns.append({
            "txn_id": txn_id, "date_id": 20240101, "product_id": pid, "warehouse": warehouse,
            "txn_type": "期初建账", "qty": int(peak * 1.0) + 10, "ref_no": OPENING_REF,
            "unit_cost": product_cost[pid],
        })

    for it in items:
        o = order_map[it["order_id"]]
        customer = customers[o["customer_id"]]
        warehouse = "华东仓" if customer["region"] in {"华东", "华南", "华北"} else "西南仓"
        if o["status"] == "已完成":
            txn_id += 1
            txns.append({
                "txn_id": txn_id, "date_id": o["order_date_id"], "product_id": it["product_id"],
                "warehouse": warehouse, "txn_type": "销售出库", "qty": -it["qty"],
                "ref_no": o["order_no"], "unit_cost": product_cost[it["product_id"]],
            })
        elif o["is_return"]:
            txn_id += 1
            txns.append({
                "txn_id": txn_id, "date_id": o["order_date_id"], "product_id": it["product_id"],
                "warehouse": warehouse, "txn_type": "退货入库", "qty": it["qty"],
                "ref_no": o["order_no"], "unit_cost": product_cost[it["product_id"]],
            })

    for po in purchases:
        if po["arrival_date_id"] > int(end.strftime("%Y%m%d")):
            continue
        warehouse = po_warehouse[po["purchase_id"]]
        txn_id += 1
        txns.append({
            "txn_id": txn_id, "date_id": po["arrival_date_id"], "product_id": po["product_id"],
            "warehouse": warehouse, "txn_type": "采购入库", "qty": po["qty"],
            "ref_no": po["purchase_no"], "unit_cost": po["total_amount"] / max(1, po["qty"]),
        })

    # 报废：约 0.4% 出库量，制造可解释的损耗
    for t in [x for x in txns if x["txn_type"] == "销售出库"]:
        if rng.random() < 0.004:
            txn_id += 1
            txns.append({
                "txn_id": txn_id, "date_id": t["date_id"], "product_id": t["product_id"],
                "warehouse": t["warehouse"], "txn_type": "报废", "qty": 1,
                "ref_no": t["ref_no"], "unit_cost": t["unit_cost"],
            })
    # 负库存修正：若某时点累计库存为负，把缺口补记到该「仓库 × 商品」的期初建账流水上。
    # 这样库存全程非负，且期初调整本身也是流水，对账口径依然成立。
    running: Dict[Tuple[int, str], int] = defaultdict(int)
    lowest: Dict[Tuple[int, str], int] = {}
    for t in sorted(txns, key=lambda x: (x["date_id"], x["txn_id"])):
        key = (t["product_id"], t["warehouse"])
        running[key] += t["qty"]
        lowest[key] = min(lowest.get(key, 0), running[key])
    openings = {(t["product_id"], t["warehouse"]): t for t in txns if t["txn_type"] == "期初建账"}
    for (pid, warehouse), low in list(lowest.items()):
        if low >= 0:
            continue
        gap = -low
        opening = openings.get((pid, warehouse))
        if opening is None:
            txn_id += 1
            opening = {"txn_id": txn_id, "date_id": 20240101, "product_id": pid, "warehouse": warehouse,
                       "txn_type": "期初建账", "qty": 0, "ref_no": OPENING_REF,
                       "unit_cost": product_cost[pid]}
            txns.append(opening)
            openings[(pid, warehouse)] = opening
        opening["qty"] += gap

    return txns


def build_snapshots(
    rng: random.Random,
    dates: List[Dict[str, Any]],
    products: List[Dict[str, Any]],
    txns: List[Dict[str, Any]],
    monthly_demand: Dict[int, int],
) -> List[Dict[str, Any]]:
    """月末库存快照：由流水累计得到，满足「期初 + 入库 − 出库 = 期末」可对账。"""
    product_cost = {p["product_id"]: p["unit_cost"] for p in products}
    days = max(1, len(dates))
    safety = {pid: max(5, int(qty / days * 0.9 * 14)) for pid, qty in monthly_demand.items()}

    month_ends: Dict[str, int] = {}
    for drow in dates:
        d = drow["full_date"]
        # 取该月最后一天：用「下月 1 号减 1 天」推，避免月末加天数跨月
        first_next = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = first_next - timedelta(days=1)
        month_ends[drow["year_month"]] = int(last.strftime("%Y%m%d"))

    ordered = sorted(txns, key=lambda t: (t["date_id"], t["txn_id"]))
    running: Dict[Tuple[int, str], int] = defaultdict(int)
    rows: List[Dict[str, Any]] = []
    snap_id = 0
    idx = 0
    for ym in sorted(month_ends):
        cutoff = month_ends[ym]
        while idx < len(ordered) and ordered[idx]["date_id"] <= cutoff:
            t = ordered[idx]
            running[(t["product_id"], t["warehouse"])] += t["qty"]
            idx += 1
        for p in products:
            for w in WAREHOUSES:
                on_hand = running.get((p["product_id"], w), 0)   # 不截断，负值会被对账暴露出来
                snap_id += 1
                rows.append({
                    "snapshot_id": snap_id, "date_id": cutoff, "product_id": p["product_id"],
                    "warehouse": w, "on_hand_qty": on_hand,
                    "safety_stock": safety.get(p["product_id"], 5),
                    "in_transit_qty": rng.randint(0, 60), "unit_cost": p["unit_cost"],
                    "inventory_value": round(on_hand * p["unit_cost"], 2),
                })
    return rows


def build_leads(rng: random.Random, dates: List[Dict[str, Any]], customers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """线索 → 商机 → 成单漏斗。AI 辅助的商机赢率更高、成单率更高、周期更短。"""
    stages = ["线索", "需求确认", "方案演示", "商务谈判", "成单", "输单"]
    win_prob = {"线索": 0.10, "需求确认": 0.25, "方案演示": 0.45, "商务谈判": 0.70, "成单": 1.00, "输单": 0.0}
    loss_reasons = ["预算不足", "竞品更优", "需求延期", "决策链未打通", "技术方案不匹配", "响应不及时"]
    rows, lead_id = [], 0
    for drow in dates:
        d = drow["full_date"]
        if d.weekday() >= 5:
            continue
        expected = 2.1 * _seasonality(d) * _growth(d, dates[0]["full_date"])
        for _ in range(max(0, int(rng.gauss(expected, expected * 0.35)))):
            lead_id += 1
            ai = 1 if rng.random() < 0.35 else 0
            # AI 辅助组：输单概率下调、成单概率上调（AI 让方案质量与跟进效率更高）
            weights = [22, 20, 18, 13, 19, 8] if ai else [24, 20, 18, 13, 15, 10]
            stage = rng.choices(stages, weights=weights)[0]
            cycle = int(max(5, rng.gauss(46, 18)))
            if ai:
                cycle = int(cycle * 0.82)
            amount = round(rng.uniform(30, 900) * 1000, 2)
            customer = rng.choice(customers)
            rows.append({
                "lead_id": lead_id,
                "lead_name": f"{customer['customer_name'][:6]}-{rng.choice(LEAD_TOPICS)}",
                "customer_id": customer["customer_id"],
                "source_channel": rng.choices(ACQUISITION, weights=[25, 20, 22, 15, 10, 8])[0],
                "created_date_id": drow["date_id"],
                "close_date_id": int((d + timedelta(days=cycle)).strftime("%Y%m%d")),
                "owner_employee_id": customer["customer_manager_id"],
                "stage": stage, "expected_amount": amount,
                "actual_amount": round(amount * rng.uniform(0.85, 1.15), 2) if stage == "成单" else 0.0,
                "win_probability": min(1.0, win_prob[stage] + (0.12 if (ai and stage in {"需求确认", "方案演示", "商务谈判"}) else 0)),
                "ai_assisted": ai, "cycle_days": cycle,
                "loss_reason": rng.choice(loss_reasons) if stage == "输单" else None,
            })
    return rows


def build_tickets(rng: random.Random, dates: List[Dict[str, Any]], customers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows, ticket_id = [], 0
    for drow in dates:
        d = drow["full_date"]
        expected = 1.5 * _seasonality(d)
        for _ in range(max(0, int(rng.gauss(expected, expected * 0.3)))):
            ticket_id += 1
            ai = 1 if rng.random() < 0.32 else 0
            frt = max(2, int(rng.gauss(18 if ai else 48, 8 if ai else 22)))
            hours = round(max(0.5, rng.gauss(7 if ai else 14, 2.5 if ai else 6)), 1)
            sat = max(1, min(5, int(round(rng.gauss(4.6 if ai else 3.9, 0.45)))))
            rows.append({
                "ticket_id": ticket_id, "customer_id": rng.choice(customers)["customer_id"],
                "created_date_id": drow["date_id"],
                "topic_type": rng.choices(TICKET_TOPICS, weights=[22, 26, 18, 20, 14])[0],
                "channel": rng.choices(["电话", "工单系统", "邮件", "在线"], weights=[30, 40, 12, 18])[0],
                "ai_handled": ai, "first_response_minutes": frt, "resolution_hours": hours,
                "satisfaction": sat,
                "converted_to_opportunity": 1 if rng.random() < (0.20 if ai else 0.10) else 0,
            })
    return rows


def build_marketing(rng: random.Random, dates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows, spend_id = [], 0
    for drow in dates:
        d = drow["full_date"]
        if d.day != 10:
            continue
        for channel, cost_base, roas in [("搜索广告", 42000, 3.2), ("行业展会", 120000, 4.6), ("内容营销", 18000, 2.4),
                                         ("转介绍激励", 6000, 6.0), ("外呼中心", 26000, 1.8), ("合作伙伴分成", 32000, 4.0)]:
            spend_id += 1
            cost = round(cost_base * _seasonality(d) * rng.uniform(0.8, 1.25), 2)
            leads = max(1, int(cost / rng.uniform(320, 900)))
            rows.append({
                "spend_id": spend_id, "date_id": drow["date_id"], "channel": channel,
                "campaign_name": f"{d.strftime('%Y-%m')} {channel}投放",
                "cost_amount": cost, "leads_count": leads,
                "revenue_attributed": round(cost * roas * rng.uniform(0.75, 1.35), 2),
            })
    return rows


def build_ai_usage(rng: random.Random, dates: List[Dict[str, Any]], employees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows, usage_id = [], 0
    month_ends: Dict[str, int] = {}
    for drow in dates:
        month_ends[drow["year_month"]] = drow["date_id"]
    for ym, date_id in month_ends.items():
        for emp in employees:
            if emp["role"] == "销售总监":
                continue
            for scenario in AI_SCENARIOS:
                usage_id += 1
                q = rng.randint(3, 18)
                accepted = int(q * rng.uniform(0.58, 0.92))
                rows.append({
                    "usage_id": usage_id, "date_id": date_id, "employee_id": emp["employee_id"],
                    "scenario": scenario, "query_count": q, "accepted_count": accepted,
                    "minutes_saved": round(accepted * rng.uniform(4.5, 11.0), 1),
                })
    return rows


def build_users() -> List[Dict[str, Any]]:
    accounts = [
        ("admin", "Admin@123456", "系统管理员", "admin", 1),
        ("analyst", "Analyst@123456", "数据分析师", "analyst", 2),
        ("sales", "Sales@123456", "销售顾问", "sales", 3),
        ("viewer", "Viewer@123456", "只读访客", "viewer", 4),
    ]
    return [{
        "user_id": uid, "username": username, "password_hash": hash_password(pwd),
        "full_name": full_name, "role": role, "employee_id": emp_id, "is_active": True,
        "created_at": datetime(2024, 1, 5, 9, 0, 0),
    } for uid, (username, pwd, full_name, role, emp_id) in enumerate(accounts, start=1)]


def run_seed(session: Session, settings: Settings, reset: bool = False) -> Dict[str, Any]:
    """幂等写入种子数据；reset=True 时先清空业务表。"""
    rng = random.Random(settings.seed_random_seed)
    start = datetime.strptime(settings.seed_start_date, "%Y-%m-%d").date()
    end = datetime.strptime(settings.seed_end_date, "%Y-%m-%d").date()

    if reset:
        # 顺序要紧：先删引用方（sys_* 与各 fact），再删维度表，否则外键约束会拦下
        session.execute(delete(m.SysRefreshToken))
        session.execute(delete(m.SysUser))
        for model in [m.FactAiUsage, m.FactMarketingSpend, m.FactCustomerTicket, m.FactLeadOpportunity,
                      m.FactInventoryTransaction, m.FactInventorySnapshot, m.FactPurchaseOrder,
                      m.FactSalesOrderItem, m.FactSalesOrder, m.DimCustomer, m.DimProduct,
                      m.DimSupplier, m.DimEmployee, m.DimDate]:
            session.execute(delete(model))
        session.flush()

    if session.query(m.DimDate).count() > 0:
        return {"status": "skipped", "reason": "数据库已有数据（reset=True 可重建）"}

    dates_all = build_dim_date(start, end)                          # 含尾部日期，承载交付日期外键
    dates = [d for d in dates_all if d["full_date"] <= end]         # 业务窗口 24 个月
    suppliers = build_suppliers(rng)
    employees = build_employees(rng, start)
    products = build_products(rng, suppliers)
    customers = build_customers(rng, employees, start)
    customer_map = {c["customer_id"]: c for c in customers}

    orders, items, demand = build_orders(rng, dates, customers, products, start)
    purchases, po_warehouse = build_purchases(rng, dates, demand, products, end)
    txns = build_transactions(rng, orders, items, purchases, po_warehouse, demand, products, customer_map, end)

    monthly_demand: Dict[int, int] = defaultdict(int)
    for it in items:
        monthly_demand[it["product_id"]] += it["qty"]
    snapshots = build_snapshots(rng, dates, products, txns, monthly_demand)

    leads = build_leads(rng, dates, customers)
    tickets = build_tickets(rng, dates, customers)
    marketing = build_marketing(rng, dates)
    ai_usage = build_ai_usage(rng, dates, employees)
    users = build_users()

    payload = [
        (m.DimDate, dates_all), (m.DimSupplier, suppliers), (m.DimEmployee, employees),
        (m.DimProduct, products), (m.DimCustomer, customers),
        (m.FactSalesOrder, orders), (m.FactSalesOrderItem, items),
        (m.FactPurchaseOrder, purchases), (m.FactInventoryTransaction, txns),
        (m.FactInventorySnapshot, snapshots), (m.FactLeadOpportunity, leads),
        (m.FactCustomerTicket, tickets), (m.FactMarketingSpend, marketing),
        (m.FactAiUsage, ai_usage), (m.SysUser, users),
    ]
    counts: Dict[str, int] = {}
    for model, rows in payload:
        session.execute(insert(model), rows)
        counts[model.__tablename__] = len(rows)
    session.commit()

    # 质量校验：库存对账（期初 + 入库 − 出库 + 退货 − 报废 = 期末快照）
    txn_sum = session.execute(
        select(
            func.sum(case((m.FactInventoryTransaction.txn_type == "期初建账", m.FactInventoryTransaction.qty), else_=0)),
            func.sum(case((m.FactInventoryTransaction.txn_type == "采购入库", m.FactInventoryTransaction.qty), else_=0)),
            func.sum(case((m.FactInventoryTransaction.txn_type == "销售出库", m.FactInventoryTransaction.qty), else_=0)),
            func.sum(case((m.FactInventoryTransaction.txn_type == "退货入库", m.FactInventoryTransaction.qty), else_=0)),
            func.sum(case((m.FactInventoryTransaction.txn_type == "报废", m.FactInventoryTransaction.qty), else_=0)),
        )
    ).one()
    last_snapshot_date = session.execute(select(func.max(m.FactInventorySnapshot.date_id))).scalar()
    ending = session.execute(
        select(func.sum(m.FactInventorySnapshot.on_hand_qty))
        .where(m.FactInventorySnapshot.date_id == last_snapshot_date)
    ).scalar()
    expected_ending = txn_sum[0] + txn_sum[1] + txn_sum[2] + txn_sum[3] + txn_sum[4]
    counts["_库存对账"] = {
        "期初建账": txn_sum[0], "采购入库": txn_sum[1], "销售出库": txn_sum[2],
        "退货入库": txn_sum[3], "报废": txn_sum[4],
        "期末快照(末月)": ending, "推算期末": expected_ending, "差异": expected_ending - ending,
        "对账通过": (expected_ending - ending) == 0,
    }
    return counts
