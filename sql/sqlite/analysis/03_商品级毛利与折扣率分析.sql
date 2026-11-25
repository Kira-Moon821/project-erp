-- ============================================================
-- 题目：商品级毛利与折扣率分析，定位「高销售低毛利」与「高折扣」的问题 SKU
-- 口径：商品级毛利率 = (SUM(revenue_amount) − SUM(cost_amount)) ÷ SUM(revenue_amount)；
--       商品级加权折扣率 = SUM(discount_rate × revenue_amount) ÷ SUM(revenue_amount)（以销售额加权）；
--       销售额/成本仅统计父订单 status='已完成'；业务窗口 2024-01-01 ~ 2025-12-31。
-- 考察点：多层级 UNION ALL 汇总（整体 → 品类 → SKU）；窗口函数 AVG() OVER (PARTITION BY category) 做同类基准对比、
--          RANK() OVER (PARTITION BY category ORDER BY ...) 做品类内排名、SUM() OVER () 做全局占比。
-- 预期结果：
--   共 86 行；列：data_level, dim_name, sku, product_name, product_status, qty, order_cnt, revenue, cost, gross_profit, gross_margin_rate, weighted_discount_rate, revenue_share_pct, category_avg_margin, discount_vs_category, margin_rank_in_category
--     整体 | ALL | NULL | NULL | NULL | 80339 | 5458 | 70,328,073.02 | 59,603,124.58 | 10,724,948.44 | 0.1525 | 0.0855 | 1 | NULL | NULL | NULL
--     品类 | 伺服电机 | NULL | NULL | NULL | 13151 | 1607 | 21,711,823.96 | 18,077,460.19 | 3,634,363.77 | 0.1674 | 0.0885 | 0.3087 | NULL | NULL | NULL
--     品类 | 变频器 | NULL | NULL | NULL | 12918 | 1621 | 15,708,367.44 | 13,712,768.57 | 1,995,598.87 | 0.127 | 0.0819 | 0.2234 | NULL | NULL | NULL
--     品类 | 工业交换机 | NULL | NULL | NULL | 12878 | 1674 | 9,843,549.9 | 8,239,565.18 | 1,603,984.72 | 0.1629 | 0.0862 | 0.14 | NULL | NULL | NULL
--     品类 | 精密减速机 | NULL | NULL | NULL | 3145 | 1666 | 7,770,976.93 | 6,705,966.03 | 1,065,010.9 | 0.137 | 0.0872 | 0.1105 | NULL | NULL | NULL
--     品类 | PLC控制器 | NULL | NULL | NULL | 3063 | 1600 | 6,029,194.12 | 4,954,528.5 | 1,074,665.62 | 0.1782 | 0.0842 | 0.0857 | NULL | NULL | NULL
--     品类 | 工业传感器 | NULL | NULL | NULL | 12878 | 1579 | 3,480,033.46 | 2,960,552.59 | 519,480.87 | 0.1493 | 0.0827 | 0.0495 | NULL | NULL | NULL
--     品类 | 电源模块 | NULL | NULL | NULL | 10513 | 1387 | 3,329,609.11 | 2,791,042.28 | 538,566.83 | 0.1618 | 0.0845 | 0.0473 | NULL | NULL | NULL
--     ...（其余 78 行略）
-- ============================================================
WITH
-- 商品 × 订单 明细（用于正确统计品类级去重订单数）
detail AS (
    SELECT
        it.product_id,
        it.order_id,
        it.qty,
        it.revenue_amount,
        it.cost_amount,
        it.discount_rate * it.revenue_amount AS disc_amount
    FROM fact_sales_order_item it
    JOIN fact_sales_order o ON o.order_id = it.order_id
    JOIN dim_date d ON d.date_id = o.order_date_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 商品级明细
item_base AS (
    SELECT
        product_id,
        SUM(qty)                              AS qty,
        COUNT(DISTINCT order_id)              AS order_cnt,
        SUM(revenue_amount)                   AS revenue,
        SUM(cost_amount)                      AS cost,
        SUM(disc_amount)                      AS disc_amount
    FROM detail
    GROUP BY product_id
),
-- SKU 级指标 + 品类内基准
sku_level AS (
    SELECT
        p.product_id,
        p.sku,
        p.product_name,
        p.category,
        p.brand,
        p.status AS product_status,
        b.qty,
        b.order_cnt,
        b.revenue,
        b.cost,
        ROUND((b.revenue - b.cost) * 1.0 / NULLIF(b.revenue, 0), 4)          AS gross_margin_rate,
        ROUND(b.disc_amount * 1.0 / NULLIF(b.revenue, 0), 4)                AS weighted_discount_rate,
        ROUND(b.revenue * 1.0 / SUM(b.revenue) OVER (), 4)                   AS revenue_share_pct,
        ROUND(AVG((b.revenue - b.cost) * 1.0 / NULLIF(b.revenue, 0)) OVER (PARTITION BY p.category), 4)
                                                                             AS category_avg_margin,
        ROUND(b.disc_amount * 1.0 / NULLIF(b.revenue, 0)
              - AVG(b.disc_amount * 1.0 / NULLIF(b.revenue, 0)) OVER (PARTITION BY p.category), 4)
                                                                             AS discount_vs_category,
        RANK() OVER (PARTITION BY p.category
                     ORDER BY (b.revenue - b.cost) * 1.0 / NULLIF(b.revenue, 0) DESC) AS margin_rank_in_category
    FROM item_base b
    JOIN dim_product p ON p.product_id = b.product_id
),
-- 品类级汇总（金额/数量来自 item_base，订单数单独按 order_id 去重，避免行数放大）
category_agg AS (
    SELECT
        p.category,
        SUM(b.qty)                       AS qty,
        SUM(b.revenue)                   AS revenue,
        SUM(b.cost)                      AS cost,
        SUM(b.disc_amount)               AS disc_amount,
        (SELECT COUNT(DISTINCT dt.order_id)
           FROM detail dt
           JOIN dim_product p2 ON p2.product_id = dt.product_id
          WHERE p2.category = p.category) AS order_cnt
    FROM item_base b
    JOIN dim_product p ON p.product_id = b.product_id
    GROUP BY p.category
)
SELECT
    'SKU' AS data_level,
    s.category                                AS dim_name,
    s.sku                                     AS sku,
    s.product_name,
    s.product_status,
    s.qty,
    s.order_cnt,
    ROUND(s.revenue, 2)                       AS revenue,
    ROUND(s.cost, 2)                          AS cost,
    ROUND(s.revenue - s.cost, 2)              AS gross_profit,
    s.gross_margin_rate,
    s.weighted_discount_rate,
    s.revenue_share_pct,
    s.category_avg_margin,
    s.discount_vs_category,
    s.margin_rank_in_category
FROM sku_level s
UNION ALL
-- 品类级汇总
SELECT
    '品类' AS data_level,
    c.category,
    NULL,
    NULL,
    NULL,
    c.qty,
    c.order_cnt,
    ROUND(c.revenue, 2),
    ROUND(c.cost, 2),
    ROUND(c.revenue - c.cost, 2),
    ROUND((c.revenue - c.cost) * 1.0 / NULLIF(c.revenue, 0), 4),
    ROUND(c.disc_amount * 1.0 / NULLIF(c.revenue, 0), 4),
    ROUND(c.revenue * 1.0 / SUM(c.revenue) OVER (), 4),
    NULL,
    NULL,
    NULL
FROM category_agg c
UNION ALL
-- 整体汇总
SELECT
    '整体' AS data_level,
    'ALL',
    NULL,
    NULL,
    NULL,
    SUM(b.qty),
    (SELECT COUNT(DISTINCT order_id) FROM detail),
    ROUND(SUM(b.revenue), 2),
    ROUND(SUM(b.cost), 2),
    ROUND(SUM(b.revenue) - SUM(b.cost), 2),
    ROUND((SUM(b.revenue) - SUM(b.cost)) * 1.0 / NULLIF(SUM(b.revenue), 0), 4),
    ROUND(SUM(b.disc_amount) * 1.0 / NULLIF(SUM(b.revenue), 0), 4),
    1.0,
    NULL,
    NULL,
    NULL
FROM item_base b
ORDER BY data_level DESC, revenue DESC;
