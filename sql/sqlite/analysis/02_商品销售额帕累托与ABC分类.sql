-- ============================================================
-- 题目：商品销售额帕累托（80/20）分析与 ABC 分类，识别核心贡献 SKU
-- 口径：商品销售额 = SUM(fact_sales_order_item.revenue_amount)，只取父订单 status='已完成'；
--       帕累托累计占比 = 按销售额降序累计销售额 ÷ 总销售额；
--       ABC 分类：累计占比 ≤ 80% 为 A（核心）、≤ 95% 为 B（常规）、其余为 C（长尾）；
--       「帕累托贡献」= 累计占比首次达到 80% 所需商品数 ÷ 商品总数。
-- 考察点：窗口函数 ROW_NUMBER 排名 + SUM() OVER (ORDER BY ... ROWS UNBOUNDED PRECEDING) 累计占比；
--          窗口内 MIN(CASE ...) 提取 80% 分界商品数；COUNT(*) OVER (PARTITION BY ...) 统计各类 SKU 数。
-- 预期结果：
--   共 77 行；列：sales_rank, sku, product_name, category, brand, product_status, qty, order_cnt, revenue, revenue_pct, cum_pct, abc_class, gross_margin_rate, pareto80_sku_seq, pareto80_sku_ratio, abc_sku_count, abc_revenue_pct
--     1 | SKU-0014 | 松下 标准型伺服电机 | 伺服电机 | 松下 | 在售 | 1795 | 197 | 3,400,061.91 | 0.0483 | 0.0483 | A-核心 | 0.2055 | 42 | 0.5455 | 41 | 0.7964
--     2 | SKU-0018 | 安川 高防护型伺服电机 | 伺服电机 | 安川 | 在售 | 1317 | 204 | 2,511,308.45 | 0.0357 | 0.0841 | A-核心 | 0.2077 | 42 | 0.5455 | 41 | 0.7964
--     3 | SKU-0013 | 汇川 高防护型伺服电机 | 伺服电机 | 汇川 | 在售 | 1512 | 197 | 2,509,210.68 | 0.0357 | 0.1197 | A-核心 | 0.1202 | 42 | 0.5455 | 41 | 0.7964
--     4 | SKU-0011 | 汇川 高精度型伺服电机 | 伺服电机 | 汇川 | 在售 | 1479 | 205 | 2,207,437.34 | 0.0314 | 0.1511 | A-核心 | 0.0906 | 42 | 0.5455 | 41 | 0.7964
--     5 | SKU-0017 | 汇川 紧凑型伺服电机 | 伺服电机 | 汇川 | 在售 | 1316 | 178 | 2,195,672.52 | 0.0312 | 0.1823 | A-核心 | 0.1931 | 42 | 0.5455 | 41 | 0.7964
--     6 | SKU-0016 | 松下 防爆型伺服电机 | 伺服电机 | 松下 | 在售 | 1286 | 174 | 2,090,350.14 | 0.0297 | 0.2121 | A-核心 | 0.0764 | 42 | 0.5455 | 41 | 0.7964
--     7 | SKU-0019 | 松下 防爆型伺服电机 | 伺服电机 | 松下 | 在售 | 1362 | 199 | 2,009,911.61 | 0.0286 | 0.2406 | A-核心 | 0.1925 | 42 | 0.5455 | 41 | 0.7964
--     8 | SKU-0050 | 施耐德 高精度型变频器 | 变频器 | 施耐德 | 在售 | 1452 | 193 | 2,002,270.19 | 0.0285 | 0.2691 | A-核心 | 0.0952 | 42 | 0.5455 | 41 | 0.7964
--     ...（其余 69 行略）
-- ============================================================
WITH
-- 商品级销售汇总（仅已完成订单）
product_sales AS (
    SELECT
        it.product_id,
        SUM(it.qty)                          AS qty,
        SUM(it.revenue_amount)               AS revenue,
        SUM(it.cost_amount)                  AS cost,
        COUNT(DISTINCT it.order_id)          AS order_cnt
    FROM fact_sales_order_item it
    JOIN fact_sales_order o ON o.order_id = it.order_id
    JOIN dim_date d ON d.date_id = o.order_date_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY it.product_id
),
-- 窗口排名 + 累计销售额
ranked AS (
    SELECT
        ps.product_id,
        p.sku,
        p.product_name,
        p.category,
        p.brand,
        p.status AS product_status,
        ps.qty,
        ps.order_cnt,
        ps.revenue,
        ps.cost,
        ROW_NUMBER() OVER (ORDER BY ps.revenue DESC, ps.product_id) AS rk,
        SUM(ps.revenue) OVER ()                                     AS total_revenue,
        SUM(ps.revenue) OVER (ORDER BY ps.revenue DESC, ps.product_id
                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_revenue
    FROM product_sales ps
    JOIN dim_product p ON p.product_id = ps.product_id
),
-- 计算占比
calc AS (
    SELECT
        r.*,
        ROUND(r.revenue * 1.0 / NULLIF(r.total_revenue, 0), 4)    AS revenue_pct,
        ROUND(r.cum_revenue * 1.0 / NULLIF(r.total_revenue, 0), 4) AS cum_pct
    FROM ranked r
)
SELECT
    c.rk                                                            AS sales_rank,
    c.sku,
    c.product_name,
    c.category,
    c.brand,
    c.product_status,
    c.qty,
    c.order_cnt,
    ROUND(c.revenue, 2)                                             AS revenue,
    c.revenue_pct,
    c.cum_pct,
    CASE
        WHEN c.cum_pct <= 0.80 THEN 'A-核心'
        WHEN c.cum_pct <= 0.95 THEN 'B-常规'
        ELSE 'C-长尾'
    END                                                             AS abc_class,
    ROUND((c.revenue - c.cost) * 1.0 / NULLIF(c.revenue, 0), 4)    AS gross_margin_rate,
    -- 帕累托 80% 分界：累计占比首次达到 80% 的商品序号
    MIN(CASE WHEN c.cum_pct >= 0.80 THEN c.rk END) OVER ()          AS pareto80_sku_seq,
    ROUND(MIN(CASE WHEN c.cum_pct >= 0.80 THEN c.rk END) OVER () * 1.0
          / COUNT(*) OVER (), 4)                                    AS pareto80_sku_ratio,
    -- 各类别 SKU 数与销售额占比
    COUNT(*) OVER (PARTITION BY
        CASE WHEN c.cum_pct <= 0.80 THEN 'A-核心'
             WHEN c.cum_pct <= 0.95 THEN 'B-常规'
             ELSE 'C-长尾' END)                                    AS abc_sku_count,
    ROUND(SUM(c.revenue) OVER (PARTITION BY
        CASE WHEN c.cum_pct <= 0.80 THEN 'A-核心'
             WHEN c.cum_pct <= 0.95 THEN 'B-常规'
             ELSE 'C-长尾' END) * 1.0
        / SUM(c.revenue) OVER (), 4)                               AS abc_revenue_pct
FROM calc c
ORDER BY c.rk;
