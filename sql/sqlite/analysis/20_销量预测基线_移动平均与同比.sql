-- ============================================================
-- 题目：销量（营收）简单预测基线——3 期移动平均 + 同比法，用于评估预测误差并作为模型下限
-- 口径：实际值 = 当月已完成订单 SUM(net_amount)（营收）与 SUM(fact_sales_order_item.qty)（销量）；
--       3 期移动平均基线 = 前 3 个月实际值的算术平均（窗口函数 ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING，
--       不含当期，避免用未来信息）；同比基线 = 去年同月实际值（LAG 12）；
--       预测误差 = 预测值 − 实际值；MAPE = AVG(ABS(误差) ÷ 实际值)；
--       业务窗口 2024-01-01 ~ 2025-12-31，共 24 个月。
-- 考察点：递归 CTE 生成 24 个月序列并 LEFT JOIN 补齐（保证每月都有行）；
--          窗口函数 AVG() OVER (ORDER BY ym ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) 算移动平均、
--          LAG(12) 算同比基线；MAPE 用 ABS() 条件聚合；
--          CASE WHEN 区分基线优劣。
-- 预期结果：
--   共 24 行；列：ym, order_cnt, actual_revenue, actual_qty, ma3_revenue_forecast, ma3_revenue_error_rate, yoy_revenue_forecast, yoy_revenue_error_rate, ma3_qty_forecast, ma3_qty_error_rate, yoy_qty_forecast, yoy_qty_error_rate, better_baseline
--     2024-01 | 140 | 5,829,501.07 | 2,066 | NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL | 基线不可用（历史期不足）
--     2024-02 | 126 | 5,259,846.48 | 1,923 | 5,829,501.07 | 0.1083 | NULL | NULL | 2,066 | 0.0744 | NULL | NULL | 3期移动平均更准
--     2024-03 | 207 | 7,882,884.95 | 2,780 | 5,544,673.78 | -0.2966 | NULL | NULL | 1,994.5 | -0.2826 | NULL | NULL | 仅移动平均可用
--     2024-04 | 198 | 10,170,772.06 | 2,935 | 6,324,077.5 | -0.3782 | NULL | NULL | 2,256.33 | -0.2312 | NULL | NULL | 仅移动平均可用
--     2024-05 | 219 | 11,693,428.72 | 3,556 | 7,771,167.83 | -0.3354 | NULL | NULL | 2,546 | -0.284 | NULL | NULL | 仅移动平均可用
--     2024-06 | 199 | 9,988,824.14 | 3,384 | 9,915,695.24 | -0.0073 | NULL | NULL | 3,090.33 | -0.0868 | NULL | NULL | 3期移动平均更准
--     2024-07 | 205 | 8,884,620.58 | 3,160 | 10,617,674.97 | 0.1951 | NULL | NULL | 3,291.67 | 0.0417 | NULL | NULL | 仅移动平均可用
--     2024-08 | 215 | 8,447,353.31 | 2,678 | 10,188,957.81 | 0.2062 | NULL | NULL | 3,366.67 | 0.2572 | NULL | NULL | 仅移动平均可用
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
-- 月度实际值
monthly_actual AS (
    SELECT
        d.year_month                                    AS ym,
        COUNT(DISTINCT o.order_id)                       AS order_cnt,
        SUM(o.net_amount)                               AS revenue,
        SUM(it.qty)                                     AS qty
    FROM fact_sales_order o
    JOIN dim_date d ON d.date_id = o.order_date_id
    JOIN fact_sales_order_item it ON it.order_id = o.order_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY d.year_month
),
-- 补齐序列并计算两种基线
series AS (
    SELECT
        m.ym,
        COALESCE(a.order_cnt, 0) AS order_cnt,
        COALESCE(a.revenue, 0)   AS revenue,
        COALESCE(a.qty, 0)       AS qty
    FROM months m
    LEFT JOIN monthly_actual a ON a.ym = m.ym
),
baselines AS (
    SELECT
        s.*,
        -- 3 期移动平均基线（前 3 期，不含当期）
        ROUND(AVG(s.revenue) OVER (ORDER BY s.ym
              ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 2) AS ma3_revenue_forecast,
        ROUND(AVG(s.qty) OVER (ORDER BY s.ym
              ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 2) AS ma3_qty_forecast,
        -- 同比基线（去年同月）
        ROUND(LAG(s.revenue, 12) OVER (ORDER BY s.ym), 2) AS yoy_revenue_forecast,
        ROUND(LAG(s.qty, 12) OVER (ORDER BY s.ym), 2)     AS yoy_qty_forecast
    FROM series s
)
SELECT
    b.ym,
    b.order_cnt,
    ROUND(b.revenue, 2)                              AS actual_revenue,
    ROUND(b.qty, 2)                                  AS actual_qty,
    b.ma3_revenue_forecast,
    ROUND((b.ma3_revenue_forecast - b.revenue) * 1.0 / NULLIF(b.revenue, 0), 4) AS ma3_revenue_error_rate,
    b.yoy_revenue_forecast,
    ROUND((b.yoy_revenue_forecast - b.revenue) * 1.0 / NULLIF(b.revenue, 0), 4) AS yoy_revenue_error_rate,
    b.ma3_qty_forecast,
    ROUND((b.ma3_qty_forecast - b.qty) * 1.0 / NULLIF(b.qty, 0), 4)           AS ma3_qty_error_rate,
    b.yoy_qty_forecast,
    ROUND((b.yoy_qty_forecast - b.qty) * 1.0 / NULLIF(b.qty, 0), 4)           AS yoy_qty_error_rate,
    CASE
        WHEN b.ma3_revenue_forecast IS NULL THEN '基线不可用（历史期不足）'
        WHEN ABS(b.ma3_revenue_forecast - b.revenue) * 1.0 / NULLIF(b.revenue, 0) <= 0.15
             AND (b.yoy_revenue_forecast IS NULL
                  OR ABS(b.yoy_revenue_forecast - b.revenue) * 1.0 / NULLIF(b.revenue, 0) > 0.15)
            THEN '3期移动平均更准'
        WHEN b.yoy_revenue_forecast IS NULL THEN '仅移动平均可用'
        WHEN ABS(b.yoy_revenue_forecast - b.revenue) * 1.0 / NULLIF(b.revenue, 0)
             < ABS(b.ma3_revenue_forecast - b.revenue) * 1.0 / NULLIF(b.revenue, 0)
            THEN '同比法更准'
        ELSE '移动平均更准'
    END                                               AS better_baseline
FROM baselines b
ORDER BY b.ym;
