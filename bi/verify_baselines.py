"""BI 资产校验脚本：核对字段名、口径与基线数值。

用途
----
1. 列出 bi/data 下每个 CSV 的**准确列名**，供 DAX / Tableau 计算字段逐字引用；
2. 校验主外键完整性（事实表外键是否都能在维度表命中）；
3. 按 docs/数据字典与业务口径.md 的口径重算全部指标，产出**期望基线**，
   供在 Power BI / Tableau 中建完报表后逐项对账；
4. 输出文件 MD5 指纹。数据重新生成后指纹会变化，此时基线需重新生成
   （本脚本即为重算入口）。

用法
----
    python bi/verify_baselines.py            # 打印报告
    python bi/verify_baselines.py --json     # 输出机器可读 JSON

依赖：仅标准库（csv / io / collections / datetime / hashlib），无需 pandas。
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime
import hashlib
import io
import json
import math
import os
import sys
from typing import Any, Dict, Iterable, List, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

# 业务窗口（数据字典 §5）
WINDOW_START = datetime.date(2024, 1, 1)
WINDOW_END = datetime.date(2025, 12, 31)

# 口径常量（数据字典 §3）
STATUS_VALID = "已完成"          # 营收类指标仅统计此状态
STATUS_REFUNDED = "已退款"       # 明确排除
STAGE_WON = "成单"               # 漏斗终点
STAGE_LOST = "输单"
FUNNEL_ORDER = ["线索", "需求确认", "方案演示", "商务谈判", "成单"]


# --------------------------------------------------------------------------
# 基础读取
# --------------------------------------------------------------------------
def read_csv(name: str) -> List[Dict[str, str]]:
    """读取单个 CSV（utf-8-sig，Excel 可直接打开）。"""
    path = os.path.join(DATA_DIR, name)
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def columns_of(name: str) -> List[str]:
    """返回 CSV 的准确列名（保持原始顺序）。"""
    path = os.path.join(DATA_DIR, name)
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        return next(reader)


def md5(name: str) -> str:
    path = os.path.join(DATA_DIR, name)
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def f2(v: str) -> float:
    return float(v)


def pct_inc(sorted_vals: Sequence[float], p: float) -> float:
    """PERCENTILE.INC（与 Excel / DAX PERCENTILEX.INC 同口径）。"""
    n = len(sorted_vals)
    if n == 0:
        raise ValueError("empty")
    pos = (n - 1) * p
    lo = math.floor(pos)
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (pos - lo) * (sorted_vals[hi] - sorted_vals[lo])


def d(x: Any, nd: int = 2) -> Any:
    return round(x, nd) if isinstance(x, float) else x


# --------------------------------------------------------------------------
# 1. 列名清单
# --------------------------------------------------------------------------
FILES = [
    "fact_sales_order_flat.csv",
    "fact_sales_order_item_flat.csv",
    "fact_inventory_snapshot_flat.csv",
    "fact_lead_opportunity_flat.csv",
    "fact_customer_ticket_flat.csv",
    "fact_marketing_spend_flat.csv",
    "fact_ai_usage_flat.csv",
    "dim_date.csv",
    "dim_customer.csv",
    "dim_employee.csv",
    "dim_product.csv",
]


def section_columns(lines: List[str]) -> Dict[str, Any]:
    lines.append("=" * 78)
    lines.append("1. 列名清单（所有 DAX / Tableau 字段必须与此逐字一致）")
    lines.append("=" * 78)
    out: Dict[str, Any] = {}
    for name in FILES:
        cols = columns_of(name)
        out[name] = cols
        lines.append(f"\n[{name}]  行数={len(read_csv(name))}  列数={len(cols)}")
        for i, c in enumerate(cols):
            lines.append(f"    {i + 1:>2}. {c}")
    return out


# --------------------------------------------------------------------------
# 2. 主外键完整性
# --------------------------------------------------------------------------
def section_keys(lines: List[str]) -> Dict[str, Any]:
    lines.append("")
    lines.append("=" * 78)
    lines.append("2. 主键唯一性与外键完整性")
    lines.append("=" * 78)
    res: Dict[str, Any] = {}

    pk_spec = {
        "dim_date.csv": "date_id",
        "dim_customer.csv": "customer_id",
        "dim_employee.csv": "employee_id",
        "dim_product.csv": "product_id",
        "fact_sales_order_flat.csv": "order_id",
        "fact_sales_order_item_flat.csv": "order_item_id",
        "fact_inventory_snapshot_flat.csv": "snapshot_id",
        "fact_lead_opportunity_flat.csv": "lead_id",
        "fact_customer_ticket_flat.csv": "ticket_id",
        "fact_marketing_spend_flat.csv": "spend_id",
        "fact_ai_usage_flat.csv": "usage_id",
    }
    for f, pk in pk_spec.items():
        vals = [r[pk] for r in read_csv(f)]
        uniq = len(set(vals))
        ok = uniq == len(vals)
        res[f] = {"pk": pk, "rows": len(vals), "unique": uniq, "unique_ok": ok}
        lines.append(f"  {'OK ' if ok else 'ERR'}  {f}.{pk}: {len(vals)} 行 / {uniq} 唯一")

    cust_ids = {r["customer_id"] for r in read_csv("dim_customer.csv")}
    emp_ids = {r["employee_id"] for r in read_csv("dim_employee.csv")}
    prod_ids = {r["product_id"] for r in read_csv("dim_product.csv")}
    order_ids = {r["order_id"] for r in read_csv("fact_sales_order_flat.csv")}

    fk_spec = [
        ("fact_sales_order_flat.csv", "customer_id", cust_ids, "dim_customer.customer_id"),
        ("fact_sales_order_flat.csv", "employee_id", emp_ids, "dim_employee.employee_id"),
        ("fact_sales_order_item_flat.csv", "customer_id", cust_ids, "dim_customer.customer_id"),
        ("fact_sales_order_item_flat.csv", "product_id", prod_ids, "dim_product.product_id"),
        ("fact_sales_order_item_flat.csv", "order_id", order_ids, "fact_sales_order.order_id"),
        ("fact_inventory_snapshot_flat.csv", "product_id", prod_ids, "dim_product.product_id"),
        ("fact_lead_opportunity_flat.csv", "customer_id", cust_ids, "dim_customer.customer_id"),
        ("fact_lead_opportunity_flat.csv", "owner_employee_id", emp_ids, "dim_employee.employee_id"),
        ("fact_customer_ticket_flat.csv", "customer_id", cust_ids, "dim_customer.customer_id"),
        ("fact_ai_usage_flat.csv", "employee_id", emp_ids, "dim_employee.employee_id"),
    ]
    for f, fk, universe, target in fk_spec:
        missing = [r[fk] for r in read_csv(f) if r[fk] not in universe]
        ok = not missing
        res.setdefault("fk", {})[f"{f}.{fk}"] = {"ok": ok, "missing": len(missing)}
        lines.append(f"  {'OK ' if ok else 'ERR'}  {f}.{fk} -> {target}：缺失 {len(missing)}")

    # 事实表已展平的维度属性必须与维度表一致（决定"单表+DAX"路线是否可信）
    cons = []
    dc = {r["customer_id"]: r for r in read_csv("dim_customer.csv")}
    for f, pairs in [
        ("fact_sales_order_flat.csv", [("customer_tier", "tier"), ("customer_industry", "industry"),
                                       ("customer_region", "region"), ("customer_channel", "channel"),
                                       ("acquisition_source", "acquisition_source")]),
        ("fact_customer_ticket_flat.csv", [("customer_tier", "tier"), ("customer_industry", "industry"),
                                           ("customer_region", "region")]),
        ("fact_lead_opportunity_flat.csv", [("customer_tier", "tier"), ("customer_industry", "industry"),
                                            ("customer_region", "region")]),
    ]:
        bad = sum(1 for r in read_csv(f) for a, b in pairs if r[a] != dc[r["customer_id"]][b])
        cons.append((f, bad))
    dp = {r["product_id"]: r for r in read_csv("dim_product.csv")}
    for f in ["fact_sales_order_item_flat.csv", "fact_inventory_snapshot_flat.csv"]:
        bad = sum(1 for r in read_csv(f)
                  for a, b in [("sku", "sku"), ("product_name", "product_name"),
                               ("category", "category"), ("brand", "brand")]
                  if r[a] != dp[r["product_id"]][b])
        cons.append((f, bad))
    de = {r["employee_id"]: r for r in read_csv("dim_employee.csv")}
    bad = sum(1 for r in read_csv("fact_sales_order_flat.csv")
              for a, b in [("sales_team", "team"), ("sales_role", "role")]
              if r[a] != de[r["employee_id"]][b])
    cons.append(("fact_sales_order_flat.csv(员工)", bad))
    res["consistency"] = {f: bad for f, bad in cons}
    lines.append("")
    lines.append("  展平属性与维度表一致性（不一致数应为 0）：")
    for f, bad in cons:
        lines.append(f"    {'OK ' if bad == 0 else 'ERR'}  {f}: {bad}")
    return res


# --------------------------------------------------------------------------
# 3. 指标基线
# --------------------------------------------------------------------------
def section_metrics(lines: List[str]) -> Dict[str, Any]:
    lines.append("")
    lines.append("=" * 78)
    lines.append("3. 指标基线（按数据字典口径重算，用于报表对账）")
    lines.append("=" * 78)
    R: Dict[str, Any] = {}

    # ---------- 销售 ----------
    so = read_csv("fact_sales_order_flat.csv")
    done = [r for r in so if r["order_status"] == STATUS_VALID]
    net = sum(f2(r["net_amount"]) for r in done)
    gross = sum(f2(r["gross_amount"]) for r in done)
    disc = sum(f2(r["discount_amount"]) for r in done)
    cost = sum(f2(r["cost_amount"]) for r in done)
    gp = sum(f2(r["gross_profit"]) for r in done)
    R["revenue"] = d(net)
    R["gross_amount"] = d(gross)
    R["discount_amount"] = d(disc)
    R["discount_rate"] = d(disc / gross, 4)
    R["cost"] = d(cost)
    R["gross_profit"] = d(gp)
    R["gross_margin"] = d(gp / net, 4)
    R["orders"] = len(done)
    R["aov"] = d(net / len(done))
    R["customers"] = len({r["customer_id"] for r in done})
    R["orders_all_status"] = len(so)
    R["status_mix"] = dict(collections.Counter(r["order_status"] for r in so))
    lines.append(f"  营收(net_amount, 仅已完成)      = {net:,.2f}")
    lines.append(f"  吊牌额 gross_amount             = {gross:,.2f}")
    lines.append(f"  折扣额 discount_amount          = {disc:,.2f}   折扣率 = {disc / gross:.2%}")
    lines.append(f"  成本 cost_amount                = {cost:,.2f}")
    lines.append(f"  毛利 gross_profit               = {gp:,.2f}   毛利率 = {gp / net:.2%}")
    lines.append(f"  订单数(仅已完成)                = {len(done)}   (全状态 {len(so)})")
    lines.append(f"  客单价 AOV                      = {net / len(done):,.2f}")
    lines.append(f"  客户数 COUNT(DISTINCT)          = {R['customers']}")
    lines.append(f"  订单状态分布                    = {R['status_mix']}")

    y = collections.Counter()
    yo = collections.Counter()
    for r in done:
        y[r["year"]] += f2(r["net_amount"])
        yo[r["year"]] += 1
    R["revenue_by_year"] = {k: d(v) for k, v in sorted(y.items())}
    R["orders_by_year"] = dict(sorted(yo.items()))
    R["yoy_2025"] = d(y["2025"] / y["2024"] - 1, 4)
    lines.append(f"  年度营收                        = {R['revenue_by_year']}")
    lines.append(f"  同比 2025 vs 2024               = {R['yoy_2025']:.2%}  (字典预期 15%~18%)")

    mm = collections.defaultdict(float)
    for r in done:
        mm[r["year_month"]] += f2(r["net_amount"])
    ordered = sorted(mm.items(), key=lambda kv: -kv[1])
    R["peak_month"] = ordered[0][0]
    R["trough_month"] = ordered[-1][0]
    R["month_revenue"] = {k: d(v) for k, v in sorted(mm.items())}
    lines.append(f"  最高月 / 最低月                 = {ordered[0][0]} ({ordered[0][1]:,.0f}) / "
                 f"{ordered[-1][0]} ({ordered[-1][1]:,.0f})  (字典预期 12月最高 / 2月最低)")

    tier = collections.defaultdict(lambda: [0, 0.0, 0.0, 0.0])
    for r in done:
        t = tier[r["customer_tier"]]
        t[0] += 1
        t[1] += f2(r["net_amount"])
        t[2] += f2(r["discount_amount"])
        t[3] += f2(r["gross_amount"])
    R["by_tier"] = {
        k: {"orders": v[0], "revenue": d(v[1]), "aov": d(v[1] / v[0]), "discount_rate": d(v[2] / v[3], 4)}
        for k, v in sorted(tier.items())
    }
    lines.append(f"  分层                            = {R['by_tier']}")

    # ---------- 商品：ABC / 帕累托 ----------
    it = read_csv("fact_sales_order_item_flat.csv")
    itd = [r for r in it if r["order_status"] == STATUS_VALID]
    agg = collections.defaultdict(float)
    for r in itd:
        agg[r["order_id"]] += f2(r["revenue_amount"])
    mismatch = sum(1 for r in done if abs(agg.get(r["order_id"], 0.0) - f2(r["net_amount"])) > 0.02)
    sk = collections.defaultdict(float)
    for r in itd:
        sk[r["sku"]] += f2(r["revenue_amount"])
    tot = sum(sk.values())
    srt = sorted(sk.items(), key=lambda kv: -kv[1])
    # 精确：累计首次达到 80% 的商品数
    cum, n80 = 0.0, 0
    for i, (_, v) in enumerate(srt, 1):
        cum += v
        if cum / tot >= 0.8:
            n80 = i
            break
    cum, abc = 0.0, collections.Counter()
    for _, v in srt:
        cum += v
        share = cum / tot
        abc["A" if share <= 0.8 else ("B" if share <= 0.95 else "C")] += 1
    R["item_reconcile_mismatch"] = mismatch
    R["skus_with_sales"] = len(sk)
    R["pareto_80_sku_count"] = n80
    R["pareto_80_sku_share"] = d(n80 / len(sk), 4)
    R["abc"] = dict(abc)
    R["abc_a_revenue_share"] = d(sum(v for _, v in srt[:abc["A"]]) / tot, 4)
    lines.append(f"  明细/订单营收对账不一致订单数    = {mismatch}  (应为 0)")
    lines.append(f"  有销售 SKU 数                   = {len(sk)}")
    lines.append(f"  帕累托：贡献 80% 营收所需 SKU 数 = {n80} ({n80 / len(sk):.2%})")
    lines.append(f"  ABC 分类 (A≤80%,B≤95%)          = {dict(abc)}   A 类营收占比 {R['abc_a_revenue_share']:.2%}")

    # ---------- 库存 ----------
    inv = read_csv("fact_inventory_snapshot_flat.csv")
    ims = sorted({r["year_month"] for r in inv})
    last = ims[-1]
    snap = [r for r in inv if r["year_month"] == last]
    end_inv = sum(f2(r["inventory_value"]) for r in snap)
    # 日均销售成本 = 成本 / 窗口自然天数（2024-01-01 ~ 2025-12-31 含首尾 = 731 天）
    days = (WINDOW_END - WINDOW_START).days + 1
    daily_cogs = cost / days
    stockout = {r["sku"] for r in snap if int(r["on_hand_qty"]) < int(r["safety_stock"])}
    sold90 = {r["sku"] for r in itd if r["order_date"] >= "2025-10-03"}
    all_sku = {r["sku"] for r in inv}
    stale = [s for s in all_sku - sold90
             if sum(int(r["on_hand_qty"]) for r in snap if r["sku"] == s) > 0]
    dp = read_csv("dim_product.csv")
    on_sale = {r["sku"] for r in dp if r["status"] == "在售"}
    R["inventory_months"] = len(ims)
    R["inventory_window"] = [ims[0], last]
    R["inventory_value_end"] = d(end_inv)
    R["daily_cogs"] = d(daily_cogs)
    R["inventory_turnover_days"] = d(end_inv / daily_cogs, 1)
    R["stockout_sku"] = len(stockout)
    R["stockout_rate"] = d(len(stockout) / len({r["sku"] for r in snap}), 4)
    R["slow_moving_sku"] = len(stale)
    R["active_rate"] = d(len({r["sku"] for r in itd} & on_sale) / len(on_sale), 4)
    lines.append(f"  库存快照月份数                  = {len(ims)}  ({ims[0]} ~ {last})")
    lines.append(f"  期末库存金额({last})             = {end_inv:,.2f}")
    lines.append(f"  日均销售成本(成本口径)           = {daily_cogs:,.2f}   (窗口 {days} 天)")
    lines.append(f"  库存周转天数                    = {end_inv / daily_cogs:.1f}")
    lines.append(f"  缺货 SKU 数 / SKU 总数          = {len(stockout)} / {len({r['sku'] for r in snap})} "
                 f"= {len(stockout) / len({r['sku'] for r in snap}):.2%}")
    lines.append(f"  滞销 SKU(近90天无销售且库存>0)  = {len(stale)}")
    lines.append(f"  动销率(有销售/在售 SKU)         = {R['active_rate']:.2%}")

    # ---------- 漏斗 ----------
    # 语义：每条线索只记录"当前所处阶段"。到达阶段 X 及以后 = 当前阶段在 X 及其之后的线索数
    #       + 输单线索（输单说明线索已走过完整管道，只是最终失败）。
    lead = read_csv("fact_lead_opportunity_flat.csv")
    cnt = collections.Counter(r["stage"] for r in lead)
    reach: Dict[str, int] = {}
    for i, s in enumerate(FUNNEL_ORDER):
        reach[s] = sum(cnt[x] for x in FUNNEL_ORDER[i:]) + cnt[STAGE_LOST]
    # 累计转化率（相对线索总数）与逐级转化率（相对上一阶段）
    conv_cum = {s: reach[s] / len(lead) for s in FUNNEL_ORDER}
    conv_step: Dict[str, float] = {}
    for i, s in enumerate(FUNNEL_ORDER):
        prev = reach[FUNNEL_ORDER[i - 1]] if i > 0 else len(lead)
        conv_step[s] = reach[s] / prev
    R["leads"] = len(lead)
    R["stage_counts"] = dict(cnt)
    R["funnel_reach"] = reach
    R["funnel_conv_cumulative"] = {k: d(v, 4) for k, v in conv_cum.items()}
    R["funnel_conv_step"] = {k: d(v, 4) for k, v in conv_step.items()}
    R["win_rate"] = d(cnt[STAGE_WON] / len(lead), 4)
    R["avg_cycle_days"] = d(sum(f2(r["cycle_days"]) for r in lead) / len(lead))
    R["avg_delivery_days"] = d(sum(f2(r["delivery_days"]) for r in done) / len(done))
    lines.append(f"  线索数                          = {len(lead)}   阶段分布 {dict(cnt)}")
    lines.append(f"  漏斗到达数(及以后)              = {reach}")
    lines.append(f"  累计转化率(占线索总数)          = {R['funnel_conv_cumulative']}")
    lines.append(f"  逐级转化率(占上一阶段)          = {R['funnel_conv_step']}")
    lines.append(f"  成单率(成单/线索总数)           = {R['win_rate']:.2%}")
    lines.append(f"  平均销售周期 cycle_days          = {R['avg_cycle_days']} 天")
    lines.append(f"  平均交付周期 delivery_days       = {R['avg_delivery_days']} 天")

    # ---------- AI 价值 ----------
    for ai_col, table, label in [("ai_assisted", "fact_lead_opportunity_flat.csv", "商机"),
                                  ("ai_handled", "fact_customer_ticket_flat.csv", "工单")]:
        rows = read_csv(table)
        grp = {}
        for flag in ("1", "0"):
            s = [r for r in rows if r[ai_col] == flag]
            grp[flag] = {"n": len(s)}
            if table.startswith("fact_lead"):
                grp[flag]["win_rate"] = d(len([r for r in s if r["stage"] == STAGE_WON]) / len(s), 4)
                grp[flag]["avg_win_probability"] = d(sum(f2(r["win_probability"]) for r in s) / len(s), 4)
                grp[flag]["avg_cycle_days"] = d(sum(f2(r["cycle_days"]) for r in s) / len(s))
            else:
                grp[flag]["avg_first_response_minutes"] = d(sum(f2(r["first_response_minutes"]) for r in s) / len(s))
                grp[flag]["avg_satisfaction"] = d(sum(f2(r["satisfaction"]) for r in s) / len(s), 4)
                grp[flag]["convert_rate"] = d(
                    len([r for r in s if r["converted_to_opportunity"] == "1"]) / len(s), 4)
        R[f"ai_{label}"] = grp
        lines.append(f"  AI {label}对比                   = {grp}")

    ai = read_csv("fact_ai_usage_flat.csv")
    R["ai_acceptance_rate"] = d(
        sum(int(r["accepted_count"]) for r in ai) / sum(int(r["query_count"]) for r in ai), 4)
    R["ai_minutes_saved"] = d(sum(f2(r["minutes_saved"]) for r in ai), 1)
    R["ai_hours_saved"] = d(sum(f2(r["minutes_saved"]) for r in ai) / 60, 2)
    row_rates = [f2(r["acceptance_rate"]) for r in ai]
    R["ai_acceptance_row_min"] = d(min(row_rates), 4)
    R["ai_acceptance_row_max"] = d(max(row_rates), 4)
    lines.append(f"  AI 采纳率(整体)                 = {R['ai_acceptance_rate']:.2%}   "
                 f"行级区间 {min(row_rates):.2%}~{max(row_rates):.2%}")
    lines.append(f"  AI 累计节省工时                  = {R['ai_hours_saved']} 小时 ({R['ai_minutes_saved']} 分钟)")

    # ---------- 营销 ----------
    ms = read_csv("fact_marketing_spend_flat.csv")
    m_cost = sum(f2(r["cost_amount"]) for r in ms)
    m_leads = sum(int(r["leads_count"]) for r in ms)
    m_rev = sum(f2(r["revenue_attributed"]) for r in ms)
    R["marketing_cost"] = d(m_cost)
    R["marketing_leads"] = m_leads
    R["cac"] = d(m_cost / m_leads)
    R["roas"] = d(m_rev / m_cost, 4)
    lines.append(f"  营销成本 / 线索数                = {m_cost:,.2f} / {m_leads}")
    lines.append(f"  CAC                              = {R['cac']}")
    lines.append(f"  ROAS                             = {R['roas']}")

    # ---------- RFM ----------
    ref = WINDOW_END
    rf = collections.defaultdict(lambda: [None, 0, 0.0])
    for r in done:
        dt = datetime.date(*map(int, r["order_date"].split("-")))
        cur = rf[r["customer_id"]]
        if cur[0] is None or dt > cur[0]:
            cur[0] = dt
        cur[1] += 1
        cur[2] += f2(r["net_amount"])
    rows = [(cid, (ref - v[0]).days, v[1], v[2]) for cid, v in rf.items()]
    Rs = sorted(r[1] for r in rows)
    Fs = sorted(r[2] for r in rows)
    Ms = sorted(r[3] for r in rows)
    R25, R50, R75 = pct_inc(Rs, .25), pct_inc(Rs, .5), pct_inc(Rs, .75)
    F25, F50, F75 = pct_inc(Fs, .25), pct_inc(Fs, .5), pct_inc(Fs, .75)
    M25, M50, M75 = pct_inc(Ms, .25), pct_inc(Ms, .5), pct_inc(Ms, .75)

    def rfm_seg(rv, fv, mv):
        rs = 4 if rv <= R25 else (3 if rv <= R50 else (2 if rv <= R75 else 1))
        fs = 4 if fv >= F75 else (3 if fv >= F50 else (2 if fv >= F25 else 1))
        ms = 4 if mv >= M75 else (3 if mv >= M50 else (2 if mv >= M25 else 1))
        if rs >= 3 and fs >= 3 and ms >= 3:
            return "重要价值客户"
        if rs >= 3 and fs >= 3 and ms < 3:
            return "重要保持客户"
        if rs >= 3 and fs < 3 and ms >= 3:
            return "重要发展客户"
        if rs >= 3 and fs < 3 and ms < 3:
            return "一般保持客户"
        if rs < 3 and fs >= 3 and ms >= 3:
            return "潜力新客"
        if rs < 3 and fs >= 3 and ms < 3:
            return "潜力成长客户"
        if rs < 3 and fs < 3 and ms >= 3:
            return "流失预警客户"
        return "沉睡客户"

    seg_cnt = collections.Counter(rfm_seg(r, f, m) for _, r, f, m in rows)
    R["rfm_quartiles"] = {"R": [d(R25), d(R50), d(R75)], "F": [d(F25), d(F50), d(F75)],
                          "M": [d(M25), d(M50), d(M75)]}
    R["rfm_segments"] = dict(seg_cnt)
    R["inactive_90d_customers"] = len([1 for _, r, _, _ in rows if r > 90])
    lines.append(f"  RFM 四分位 R={d(R25)}/{d(R50)}/{d(R75)}  "
                 f"F={d(F25)}/{d(F50)}/{d(F75)}  M={d(M25)}/{d(M50)}/{d(M75)}")
    lines.append(f"  RFM 分层分布                    = {dict(seg_cnt)}")
    lines.append(f"  近 90 天未成交客户数            = {R['inactive_90d_customers']}  (数据集内全部客户近 90 天有成交)")

    # ---------- 维度窗口 ----------
    dd = read_csv("dim_date.csv")
    R["dim_date_range"] = [dd[0]["full_date"], dd[-1]["full_date"]]
    R["dim_date_rows"] = len(dd)
    R["dim_customer_rows"] = len(read_csv("dim_customer.csv"))
    R["dim_employee_rows"] = len(read_csv("dim_employee.csv"))
    R["dim_product_rows"] = len(read_csv("dim_product.csv"))
    lines.append(f"  dim_date 覆盖                    = {dd[0]['full_date']} ~ {dd[-1]['full_date']} "
                 f"({len(dd)} 天，含交付日期尾部 90 天)")
    lines.append(f"  维度表行数 客户/员工/商品        = {R['dim_customer_rows']}/"
                 f"{R['dim_employee_rows']}/{R['dim_product_rows']}")
    return R


# --------------------------------------------------------------------------
# 4. 业务规律复核
# --------------------------------------------------------------------------
def section_rules(lines: List[str], R: Dict[str, Any]) -> Dict[str, Any]:
    lines.append("")
    lines.append("=" * 78)
    lines.append("4. 数据字典 §4 业务规律复核")
    lines.append("=" * 78)
    checks = []
    checks.append(("年度增长 15%~18%", 0.15 <= R["yoy_2025"] <= 0.18, f"{R['yoy_2025']:.2%}"))
    checks.append(("季节性：12月最高", R["peak_month"].endswith("-12"), R["peak_month"]))
    checks.append(("季节性：2月最低", R["trough_month"].endswith("-02"), R["trough_month"]))
    a = R["by_tier"].get("A", {})
    others = [v["aov"] for k, v in R["by_tier"].items() if k != "A"]
    checks.append(("A类客单价最高", a.get("aov", 0) >= max(others) if others else True, a.get("aov")))
    dr = R["by_tier"].get("A", {}).get("discount_rate", 0)
    other_dr = [v["discount_rate"] for k, v in R["by_tier"].items() if k != "A"]
    checks.append(("A类折扣率最高", dr >= max(other_dr) if other_dr else True, f"{dr:.2%}"))
    ai_l, ai_t = R["ai_商机"], R["ai_工单"]
    checks.append(("AI商机成单率高于对照", ai_l["1"]["win_rate"] > ai_l["0"]["win_rate"],
                   f"{ai_l['1']['win_rate']:.2%} > {ai_l['0']['win_rate']:.2%}"))
    checks.append(("AI商机平均赢率更高", ai_l["1"]["avg_win_probability"] > ai_l["0"]["avg_win_probability"],
                   f"{ai_l['1']['avg_win_probability']} > {ai_l['0']['avg_win_probability']}"))
    checks.append(("AI商机周期更短", ai_l["1"]["avg_cycle_days"] < ai_l["0"]["avg_cycle_days"],
                   f"{ai_l['1']['avg_cycle_days']} < {ai_l['0']['avg_cycle_days']}"))
    checks.append(("AI工单首响更快", ai_t["1"]["avg_first_response_minutes"] < ai_t["0"]["avg_first_response_minutes"],
                   f"{ai_t['1']['avg_first_response_minutes']} < {ai_t['0']['avg_first_response_minutes']}"))
    checks.append(("AI工单满意度更高", ai_t["1"]["avg_satisfaction"] > ai_t["0"]["avg_satisfaction"],
                   f"{ai_t['1']['avg_satisfaction']} > {ai_t['0']['avg_satisfaction']}"))
    checks.append(("AI工单转商机率更高", ai_t["1"]["convert_rate"] > ai_t["0"]["convert_rate"],
                   f"{ai_t['1']['convert_rate']:.2%} > {ai_t['0']['convert_rate']:.2%}"))
    out = {}
    for name, ok, actual in checks:
        out[name] = {"ok": bool(ok), "actual": actual}
        lines.append(f"  {'OK ' if ok else 'WARN'}  {name}  ->  {actual}")
    lines.append("")
    lines.append("  注：字典 §4 称 AI 采纳率「约 58%~92%」，实际整体为 "
                 f"{R['ai_acceptance_rate']:.2%}，行级区间 {R['ai_acceptance_row_min']:.2%}~"
                 f"{R['ai_acceptance_row_max']:.2%}（种子生成参数为 0.58~0.92，取整后行级离散）。")
    lines.append("      按字典 §3 口径「accepted_count/query_count」实现，整体采纳率即为上表数值。")
    return out


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="ERP BI 资产校验")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if not os.path.isdir(DATA_DIR):
        print(f"[ERROR] 数据目录不存在：{DATA_DIR}", file=sys.stderr)
        return 2

    lines: List[str] = []
    lines.append("ERP 经营分析实验室 — BI 资产校验")
    lines.append(f"数据目录：{DATA_DIR}")
    lines.append(f"数据窗口：{WINDOW_START} ~ {WINDOW_END}")
    lines.append("")

    cols = section_columns(lines)
    keys = section_keys(lines)
    metrics = section_metrics(lines)
    rules = section_rules(lines, metrics)

    lines.append("")
    lines.append("=" * 78)
    lines.append("5. 文件 MD5 指纹（数据重新生成后指纹变化，需重跑本脚本刷新基线）")
    lines.append("=" * 78)
    fps = {}
    for name in FILES:
        h = md5(name)
        fps[name] = h
        lines.append(f"  {h}  {name}")

    report = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "data_window": [str(WINDOW_START), str(WINDOW_END)],
        "columns": cols,
        "keys": keys,
        "metrics": metrics,
        "rules": rules,
        "md5": fps,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n".join(lines))
        print("\n提示：把上面的基线数值与 BI 报表读数逐项核对，全部一致即说明口径实现正确。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
