-- ============================================================
-- 题目：库存收发存对账——验证「期初 + 入库 − 出库 = 期末快照」是否差异为 0
-- 口径：期初建账 / 采购入库 / 退货入库 / 销售出库 / 报废 五类流水的 qty 按「仓库 × SKU × 月份」汇总；
--       销售出库 qty 存为负数、报废 qty 存为正数（seed 口径），故净额 = SUM(qty)；
--       期末快照 = fact_inventory_snapshot.on_hand_qty（月末日）；
--       对账差异 = 累计推算期末 − 快照期末，逐「仓库 × SKU × 月」核对并汇总到月；
--       业务窗口 2024-01-01 ~ 2025-12-31。
-- 考察点：递归 CTE 逐月滚动结存（上期期末 + 本期净变动 = 本期期末），实现真正的「收发存」对账；
--          窗口函数 SUM() OVER (PARTITION BY 仓库,SKU ORDER BY 月份) 做累计余额；
--          条件聚合 CASE WHEN 分流五类流水；HAVING 筛出差异行。
-- 预期结果：
--   共 24 行；列：ym, opening_qty, purchase_in_qty, return_in_qty, sales_out_qty, scrap_qty, net_change_qty, calc_ending_qty, snapshot_ending_qty, diff_qty, recon_row_cnt, diff_row_cnt, recon_status, cum_diff_qty
--     2024-01 | 13380 | 2178 | 97 | -2066 | 1 | 13590 | 13590 | 13590 | 0 | 154 | 0 | 对账通过 | 0
--     2024-02 | 0 | 2050 | 47 | -1923 | 1 | 175 | 12495 | 12495 | 0 | 137 | 0 | 对账通过 | 0
--     2024-03 | 0 | 3195 | 88 | -2780 | 4 | 507 | 13638 | 13638 | 0 | 147 | 0 | 对账通过 | 0
--     2024-04 | 0 | 3140 | 25 | -2935 | 1 | 231 | 14113 | 14113 | 0 | 149 | 0 | 对账通过 | 0
--     2024-05 | 0 | 3804 | 0 | -3556 | 2 | 250 | 14141 | 14141 | 0 | 147 | 0 | 对账通过 | 0
--     2024-06 | 0 | 3247 | 41 | -3384 | 0 | -96 | 14450 | 14450 | 0 | 152 | 0 | 对账通过 | 0
--     2024-07 | 0 | 3661 | 20 | -3160 | 2 | 523 | 14766 | 14766 | 0 | 149 | 0 | 对账通过 | 0
--     2024-08 | 0 | 3166 | 23 | -2678 | 1 | 512 | 14934 | 14934 | 0 | 147 | 0 | 对账通过 | 0
--     ...（其余 16 行略）
-- ============================================================
WITH RECURSIVE
-- 递归 CTE：生成 2024-01 ~ 2025-12 的月份序列（日期序列补齐）
months(ym) AS (
    SELECT '2024-01'
    UNION ALL
    SELECT strftime('%Y-%m', date(ym || '-01', '+1 month'))
    FROM months
    WHERE ym < '2025-12'
),
-- 五类流水分流汇总（仓库 × SKU × 月）
flow AS (
    SELECT
        t.product_id,
        t.warehouse,
        d.year_month                                                             AS ym,
        SUM(CASE WHEN t.txn_type = '期初建账' THEN t.qty ELSE 0 END)            AS opening_qty,
        SUM(CASE WHEN t.txn_type = '采购入库' THEN t.qty ELSE 0 END)            AS purchase_in_qty,
        SUM(CASE WHEN t.txn_type = '退货入库' THEN t.qty ELSE 0 END)            AS return_in_qty,
        SUM(CASE WHEN t.txn_type = '销售出库' THEN t.qty ELSE 0 END)            AS sales_out_qty,
        SUM(CASE WHEN t.txn_type = '报废'     THEN t.qty ELSE 0 END)            AS scrap_qty,
        SUM(t.qty)                                                              AS net_change_qty
    FROM fact_inventory_transaction t
    JOIN dim_date d ON d.date_id = t.date_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY t.product_id, t.warehouse, d.year_month
),
-- 窗口函数累计余额：期初 + 累计净变动 = 推算期末
running AS (
    SELECT
        f.*,
        SUM(f.net_change_qty) OVER (
            PARTITION BY f.product_id, f.warehouse
            ORDER BY f.ym
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS calc_ending_qty
    FROM flow f
),
-- 月末快照（仓库 × SKU）
snap AS (
    SELECT
        s.product_id,
        s.warehouse,
        d.year_month                   AS ym,
        SUM(s.on_hand_qty)             AS snapshot_ending_qty
    FROM fact_inventory_snapshot s
    JOIN dim_date d ON d.date_id = s.date_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY s.product_id, s.warehouse, d.year_month
),
-- 逐「仓库 × SKU × 月」核对
recon_rows AS (
    SELECT
        r.ym,
        r.warehouse,
        r.product_id,
        r.opening_qty,
        r.purchase_in_qty,
        r.return_in_qty,
        r.sales_out_qty,
        r.scrap_qty,
        r.net_change_qty,
        r.calc_ending_qty,
        sp.snapshot_ending_qty,
        r.calc_ending_qty - sp.snapshot_ending_qty AS diff_qty
    FROM running r
    JOIN snap sp
      ON sp.product_id = r.product_id
     AND sp.warehouse = r.warehouse
     AND sp.ym = r.ym
),
-- 月度汇总（各流水类型合计 + 差异）
monthly_recon AS (
    SELECT
        r.ym,
        SUM(r.opening_qty)            AS opening_qty,
        SUM(r.purchase_in_qty)        AS purchase_in_qty,
        SUM(r.return_in_qty)          AS return_in_qty,
        SUM(r.sales_out_qty)          AS sales_out_qty,
        SUM(r.scrap_qty)              AS scrap_qty,
        SUM(r.net_change_qty)         AS net_change_qty,
        SUM(r.calc_ending_qty)        AS calc_ending_qty,
        SUM(r.snapshot_ending_qty)    AS snapshot_ending_qty,
        SUM(r.diff_qty)               AS diff_qty,
        COUNT(*)                      AS recon_row_cnt,
        SUM(CASE WHEN r.diff_qty <> 0 THEN 1 ELSE 0 END) AS diff_row_cnt
    FROM recon_rows r
    GROUP BY r.ym
)
SELECT
    m.ym,
    m.opening_qty,
    m.purchase_in_qty,
    m.return_in_qty,
    m.sales_out_qty,
    m.scrap_qty,
    m.net_change_qty,
    m.calc_ending_qty,
    m.snapshot_ending_qty,
    m.diff_qty,
    m.recon_row_cnt,
    m.diff_row_cnt,
    CASE
        WHEN m.diff_qty = 0 AND m.diff_row_cnt = 0 THEN '对账通过'
        ELSE '存在差异'
    END                                                    AS recon_status,
    -- 累计差异（窗口函数，整期是否全部对平）
    SUM(m.diff_qty) OVER (ORDER BY m.ym)                   AS cum_diff_qty
FROM monthly_recon m
ORDER BY m.ym;
