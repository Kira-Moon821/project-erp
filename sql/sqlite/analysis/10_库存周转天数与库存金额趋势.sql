-- ============================================================
-- 题目：库存周转天数与库存金额月度趋势，评估资金占用效率
-- 口径：期末库存金额 = SUM(fact_inventory_snapshot.inventory_value) 按月末快照日；
--       日均销售成本（成本口径，不用售价）= 当月已完成订单 SUM(cost_amount) ÷ 当月自然天数；
--       库存周转天数 = 期末库存金额 ÷ 日均销售成本；动销率 = 当月有销售的 SKU 数 ÷ 在售 SKU 数；
--       库存快照月末日期由 dim_date 的月末日期确定，业务窗口 2024-01-01 ~ 2025-12-31。
-- 考察点：递归 CTE 生成 24 个月日期序列并 LEFT JOIN 补齐（保证缺月也出现）；
--          窗口函数 LAG() 做库存金额环比、AVG() OVER (ORDER BY ... ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) 算 3 期均线；
--          条件聚合算动销率；RANK() 对周转天数排名。
-- 预期结果：
--   共 24 行；列：ym, month_end, on_hand_qty, in_transit_qty, inventory_value, monthly_sales_cost, daily_sales_cost, turnover_days, inventory_mom_growth, ma3_inventory_value, sell_through_rate, turnover_rank
--     2024-01 | 2024-01-31 | 13590 | 4859 | 10,408,822.24 | 5,041,093.81 | 162,615.93 | 64 | NULL | 10,408,822.24 | 0.987 | 6
--     2024-02 | 2024-01-31 | 13590 | 4859 | 10,408,822.24 | 4,467,969.86 | 144,128.06 | 72.2 | 0 | 10,408,822.24 | 1 | 3
--     2024-03 | 2024-02-29 | 13765 | 4499 | 10,881,719.63 | 6,800,059.33 | 234,484.8 | 46.4 | 0.0454 | 10,566,454.7 | 1 | 17
--     2024-04 | 2024-03-31 | 14272 | 4850 | 11,542,547.14 | 8,820,354.18 | 284,527.55 | 40.6 | 0.0607 | 10,944,363 | 1 | 21
--     2024-05 | 2024-04-30 | 14503 | 4867 | 11,732,030.71 | 9,728,116.8 | 324,270.56 | 36.2 | 0.0164 | 11,385,432.49 | 1 | 24
--     2024-06 | 2024-05-31 | 14753 | 4644 | 12,136,298.73 | 8,373,577.53 | 270,115.4 | 44.9 | 0.0345 | 11,803,625.53 | 1 | 18
--     2024-07 | 2024-06-30 | 14657 | 4929 | 12,393,480.23 | 7,556,488.48 | 251,882.95 | 49.2 | 0.0212 | 12,087,269.89 | 1 | 14
--     2024-08 | 2024-07-31 | 15180 | 4709 | 12,795,772.22 | 7,224,581.79 | 233,051.03 | 54.9 | 0.0325 | 12,441,850.39 | 1 | 10
--     ...（其余 16 行略）
-- ============================================================
WITH RECURSIVE
-- 递归 CTE：生成 2024-01 ~ 2025-12 的月末日期序列（日期序列补齐）
months(ym, month_end) AS (
    SELECT '2024-01', '2024-01-31'
    UNION ALL
    SELECT strftime('%Y-%m', date(ym || '-01', '+1 month')),
           date(date(ym || '-01', '+1 month'), '-1 day')
    FROM months
    WHERE ym < '2025-12'
),
-- 月末库存快照汇总
snap AS (
    SELECT
        m.ym,
        m.month_end,
        COALESCE(SUM(s.on_hand_qty), 0)      AS on_hand_qty,
        COALESCE(SUM(s.inventory_value), 0)  AS inventory_value,
        COALESCE(SUM(s.in_transit_qty), 0)   AS in_transit_qty
    FROM months m
    LEFT JOIN dim_date d ON d.full_date = m.month_end
    LEFT JOIN fact_inventory_snapshot s ON s.date_id = d.date_id
    GROUP BY m.ym, m.month_end
),
-- 当月销售成本与动销 SKU 数
month_sales AS (
    SELECT
        d.year_month                                AS ym,
        SUM(o.cost_amount)                          AS cost_amount,
        COUNT(DISTINCT it.product_id)               AS sold_sku_cnt,
        COUNT(DISTINCT d.full_date)                 AS active_days
    FROM fact_sales_order o
    JOIN dim_date d ON d.date_id = o.order_date_id
    JOIN fact_sales_order_item it ON it.order_id = o.order_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY d.year_month
),
-- 在售 SKU 总数（基准分母）
active_sku AS (
    SELECT COUNT(*) AS active_sku_cnt
    FROM dim_product
    WHERE status = '在售'
),
-- 合并并计算指标
joined AS (
    SELECT
        s.ym,
        s.month_end,
        s.on_hand_qty,
        s.in_transit_qty,
        ROUND(s.inventory_value, 2)                    AS inventory_value,
        COALESCE(ms.cost_amount, 0)                    AS cost_amount,
        COALESCE(ms.sold_sku_cnt, 0)                   AS sold_sku_cnt,
        (SELECT active_sku_cnt FROM active_sku)        AS active_sku_cnt,
        CAST(strftime('%d', s.month_end) AS INTEGER)   AS days_in_month
    FROM snap s
    LEFT JOIN month_sales ms ON ms.ym = s.ym
)
SELECT
    j.ym,
    j.month_end,
    j.on_hand_qty,
    j.in_transit_qty,
    j.inventory_value,
    ROUND(j.cost_amount, 2)                                             AS monthly_sales_cost,
    ROUND(j.cost_amount * 1.0 / NULLIF(j.days_in_month, 0), 2)           AS daily_sales_cost,
    -- 库存周转天数 = 期末库存金额 ÷ 日均销售成本
    ROUND(j.inventory_value / NULLIF(j.cost_amount * 1.0 / j.days_in_month, 0), 1) AS turnover_days,
    -- 库存金额环比
    ROUND((j.inventory_value - LAG(j.inventory_value) OVER (ORDER BY j.ym)) * 1.0
          / NULLIF(LAG(j.inventory_value) OVER (ORDER BY j.ym), 0), 4)    AS inventory_mom_growth,
    -- 3 期移动平均库存金额
    ROUND(AVG(j.inventory_value) OVER (ORDER BY j.ym
          ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2)                  AS ma3_inventory_value,
    ROUND(j.sold_sku_cnt * 1.0 / NULLIF(j.active_sku_cnt, 0), 4)         AS sell_through_rate,
    RANK() OVER (ORDER BY j.inventory_value / NULLIF(j.cost_amount * 1.0 / j.days_in_month, 0) DESC) AS turnover_rank
FROM joined j
ORDER BY j.ym;
