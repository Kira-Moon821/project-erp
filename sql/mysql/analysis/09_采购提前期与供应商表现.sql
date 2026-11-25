-- ============================================================
-- 题目：采购提前期与供应商表现评估，识别交付不稳定、需扶持或替换的供应商
-- 口径：实际提前期 = 到货日期 − 下单日期（通过 dim_date 的 full_date 做 julianday 差值，
--       date_id 是 YYYYMMDD 整数，不能直接相减）；已入库采购单 status='已入库' 计入履约评估；
--       准交率 = 实际提前期 ≤ 供应商标准货期 lead_time_days 的比例；
--       提前期偏差 = 实际提前期 − 标准货期（正数=超期）；业务窗口按下单日 2024-01-01 ~ 2025-12-31。
-- 考察点：CTE 拆分「下单日期/到货日期」两路自连接（dim_date 自关联）；
--          窗口函数 RANK() OVER (ORDER BY ...) 做供应商排名、SUM() OVER () 计算采购金额占比；
--          条件聚合算准交率；CASE WHEN 分级供应商。
-- 预期结果：
--   共 10 行；列：supplier_id, supplier_name, supplier_region, rating, standard_lead_days, po_cnt, total_qty, total_amount, amount_share_pct, avg_actual_lead_days, min_lead_days, max_lead_days, avg_lead_gap_days, on_time_rate, lead_days_rank, amount_rank, supplier_grade
--     7 | 晟远科技 | 华北 | 4 | 12 | 595 | 13523 | 9,742,731.2 | 0.1444 | 17.08 | 5 | 30 | 5.08 | 0.3513 | 10 | 1 | 中-延迟偏高
--     4 | 华宇传动 | 华东 | 4 | 23 | 548 | 12724 | 9,309,114.24 | 0.1379 | 17.63 | 5 | 30 | -5.37 | 0.7226 | 5 | 2 | 良-偶有延迟
--     5 | 博联电气 | 华东 | 3.6 | 7 | 354 | 9745 | 9,063,701.85 | 0.1343 | 17.51 | 5 | 30 | 10.51 | 0.1102 | 6 | 3 | 差-需扶持或替换
--     3 | 锐川机电 | 华东 | 4.5 | 26 | 410 | 9648 | 7,949,338.65 | 0.1178 | 17.4 | 5 | 30 | -8.6 | 0.8366 | 7 | 4 | 优-稳定供应
--     9 | 普林气动 | 华南 | 4 | 27 | 413 | 10793 | 7,012,985.4 | 0.1039 | 17.82 | 5 | 30 | -9.18 | 0.8789 | 2 | 5 | 优-稳定供应
--     10 | 凯盛电子 | 西南 | 3.6 | 9 | 274 | 6643 | 6,609,466.89 | 0.0979 | 17.77 | 5 | 30 | 8.77 | 0.1898 | 3 | 6 | 差-需扶持或替换
--     2 | 中启自动化 | 华南 | 3.5 | 12 | 311 | 7701 | 6,206,412.57 | 0.092 | 17.33 | 5 | 30 | 5.33 | 0.299 | 8 | 7 | 中-延迟偏高
--     1 | 恒达精密 | 华东 | 4.5 | 5 | 314 | 6189 | 6,017,137.44 | 0.0892 | 18.03 | 5 | 30 | 13.03 | 0.0255 | 1 | 8 | 差-需扶持或替换
--     ...（其余 2 行略）
-- ============================================================
WITH
-- 采购单 + 下单日期 + 到货日期（dim_date 自连接）
po_base AS (
    SELECT
        p.purchase_id,
        p.purchase_no,
        p.supplier_id,
        p.product_id,
        p.qty,
        p.total_amount,
        p.status,
        d_order.full_date                                       AS order_date,
        d_arrive.full_date                                      AS arrival_date,
        CAST(DATEDIFF(d_arrive.full_date, d_order.full_date) AS SIGNED) AS actual_lead_days,
        d_order.year_month                                      AS order_ym
    FROM fact_purchase_order p
    JOIN dim_date d_order  ON d_order.date_id  = p.order_date_id
    JOIN dim_date d_arrive ON d_arrive.date_id = p.arrival_date_id
    WHERE d_order.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 已入库采购单的履约明细
fulfilled AS (
    SELECT
        b.*,
        s.supplier_name,
        s.region AS supplier_region,
        s.lead_time_days AS standard_lead_days,
        s.rating
    FROM po_base b
    JOIN dim_supplier s ON s.supplier_id = b.supplier_id
    WHERE b.status = '已入库'
),
-- 供应商级汇总
supplier_agg AS (
    SELECT
        f.supplier_id,
        f.supplier_name,
        f.supplier_region,
        f.rating,
        f.standard_lead_days,
        COUNT(*)                                                            AS po_cnt,
        SUM(f.qty)                                                          AS total_qty,
        SUM(f.total_amount)                                                AS total_amount,
        AVG(CAST(f.actual_lead_days AS DOUBLE))                                            AS avg_actual_lead_days,
        MIN(f.actual_lead_days)                                            AS min_lead_days,
        MAX(f.actual_lead_days)                                            AS max_lead_days,
        SUM(CASE WHEN f.actual_lead_days <= f.standard_lead_days THEN 1 ELSE 0 END) AS on_time_po_cnt
    FROM fulfilled f
    GROUP BY f.supplier_id, f.supplier_name, f.supplier_region, f.rating, f.standard_lead_days
)
SELECT
    s.supplier_id,
    s.supplier_name,
    s.supplier_region,
    s.rating,
    s.standard_lead_days,
    s.po_cnt,
    s.total_qty,
    ROUND(s.total_amount, 2)                                              AS total_amount,
    ROUND(s.total_amount * 1.0 / SUM(s.total_amount) OVER (), 4)           AS amount_share_pct,
    ROUND(s.avg_actual_lead_days, 2)                                      AS avg_actual_lead_days,
    s.min_lead_days,
    s.max_lead_days,
    ROUND(s.avg_actual_lead_days - s.standard_lead_days, 2)               AS avg_lead_gap_days,
    ROUND(s.on_time_po_cnt * 1.0 / NULLIF(s.po_cnt, 0), 4)                AS on_time_rate,
    RANK() OVER (ORDER BY s.avg_actual_lead_days DESC)                    AS lead_days_rank,
    RANK() OVER (ORDER BY s.total_amount DESC)                             AS amount_rank,
    CASE
        WHEN s.avg_actual_lead_days <= s.standard_lead_days
             AND s.on_time_po_cnt * 1.0 / NULLIF(s.po_cnt, 0) >= 0.80 THEN '优-稳定供应'
        WHEN s.avg_actual_lead_days <= s.standard_lead_days * 1.3        THEN '良-偶有延迟'
        WHEN s.avg_actual_lead_days <= s.standard_lead_days * 1.6        THEN '中-延迟偏高'
        ELSE '差-需扶持或替换'
    END                                                                    AS supplier_grade
FROM supplier_agg s
ORDER BY s.total_amount DESC;
