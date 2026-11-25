-- ============================================================
-- 题目：内部 AI 助手采纳率与节省工时分析，量化 AI 工具的内部 ROI
-- 口径：采纳率 = SUM(accepted_count) ÷ SUM(query_count)（口径文档）；节省工时 = SUM(minutes_saved) ÷ 60；
--       人均节省工时 = SUM(minutes_saved) ÷ 60 ÷ 活跃使用人数；人均查询数 = SUM(query_count) ÷ 人数；
--       使用记录按 date_id 落在业务窗口 2024-01-01 ~ 2025-12-31；场景 scenario 分三类。
-- 考察点：条件聚合算采纳率；窗口函数 RANK() OVER (PARTITION BY 维度 ORDER BY 采纳率 DESC) 做组内排名、
--          LAG() 做采纳率月度环比、SUM() OVER () 计算工时占比；CTE 多维度 UNION ALL 合并。
-- 预期结果：
--   共 33 行；列：scope, dim_type, dim_value, usage_record_cnt, active_user_cnt, total_query_count, total_accepted_count, acceptance_rate, hours_saved, hours_saved_per_user, queries_per_user, hours_share_pct, acceptance_rank_in_dim, acceptance_rate_mom_change
--     月度趋势 | 月度 | 2024-01 | NULL | 17 | 546 | 388 | 0.7106 | 47.6 | 2.8 | NULL | NULL | NULL | NULL
--     月度趋势 | 月度 | 2024-02 | NULL | 17 | 492 | 343 | 0.6972 | 45 | 2.6 | NULL | NULL | NULL | -0.0134
--     月度趋势 | 月度 | 2024-03 | NULL | 17 | 538 | 372 | 0.6914 | 47.2 | 2.8 | NULL | NULL | NULL | -0.0058
--     月度趋势 | 月度 | 2024-04 | NULL | 17 | 566 | 401 | 0.7085 | 47.7 | 2.8 | NULL | NULL | NULL | 0.0171
--     月度趋势 | 月度 | 2024-05 | NULL | 17 | 612 | 434 | 0.7092 | 53.7 | 3.2 | NULL | NULL | NULL | 0.0007
--     月度趋势 | 月度 | 2024-06 | NULL | 17 | 565 | 396 | 0.7009 | 51 | 3 | NULL | NULL | NULL | -0.0083
--     月度趋势 | 月度 | 2024-07 | NULL | 17 | 536 | 377 | 0.7034 | 48.9 | 2.9 | NULL | NULL | NULL | 0.0025
--     月度趋势 | 月度 | 2024-08 | NULL | 17 | 574 | 395 | 0.6882 | 52.6 | 3.1 | NULL | NULL | NULL | -0.0152
--     ...（其余 25 行略）
-- ============================================================
WITH
-- 窗口内使用记录 + 员工/团队信息
usage_base AS (
    SELECT
        u.usage_id,
        u.scenario,
        u.query_count,
        u.accepted_count,
        u.minutes_saved,
        d.year_month AS ym,
        e.employee_id,
        e.employee_name,
        e.team
    FROM fact_ai_usage u
    JOIN dim_date d ON d.date_id = u.date_id
    JOIN dim_employee e ON e.employee_id = u.employee_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 多维度纵向合并
unioned AS (
    SELECT '整体' AS dim_type, 'ALL' AS dim_value, * FROM usage_base
    UNION ALL
    SELECT '使用场景', scenario, * FROM usage_base
    UNION ALL
    SELECT '团队', team, * FROM usage_base
),
-- 维度汇总
dim_agg AS (
    SELECT
        u.dim_type,
        u.dim_value,
        COUNT(*)                                       AS usage_record_cnt,
        COUNT(DISTINCT u.employee_id)                  AS active_user_cnt,
        SUM(u.query_count)                             AS total_query_count,
        SUM(u.accepted_count)                          AS total_accepted_count,
        SUM(u.minutes_saved)                           AS total_minutes_saved
    FROM unioned u
    GROUP BY u.dim_type, u.dim_value
),
-- 计算指标
metrics AS (
    SELECT
        a.*,
        ROUND(a.total_accepted_count * 1.0 / NULLIF(a.total_query_count, 0), 4) AS acceptance_rate,
        ROUND(a.total_minutes_saved / 60.0, 1)                                AS hours_saved,
        ROUND(a.total_minutes_saved / 60.0 / NULLIF(a.active_user_cnt, 0), 1) AS hours_saved_per_user,
        ROUND(a.total_query_count * 1.0 / NULLIF(a.active_user_cnt, 0), 1)    AS queries_per_user
    FROM dim_agg a
),
-- 月度趋势（用于采纳率环比）
monthly AS (
    SELECT
        u.ym,
        COUNT(DISTINCT u.employee_id)                  AS active_user_cnt,
        SUM(u.query_count)                             AS total_query_count,
        SUM(u.accepted_count)                          AS total_accepted_count,
        SUM(u.minutes_saved)                           AS total_minutes_saved
    FROM usage_base u
    GROUP BY u.ym
),
monthly_metrics AS (
    SELECT
        m.ym,
        m.active_user_cnt,
        m.total_query_count,
        m.total_accepted_count,
        ROUND(m.total_accepted_count * 1.0 / NULLIF(m.total_query_count, 0), 4) AS acceptance_rate,
        ROUND(m.total_minutes_saved / 60.0, 1)                                AS hours_saved,
        ROUND(m.total_minutes_saved / 60.0 / NULLIF(m.active_user_cnt, 0), 1) AS hours_saved_per_user
    FROM monthly m
)
SELECT
    '维度汇总'                              AS scope,
    x.dim_type,
    x.dim_value,
    x.usage_record_cnt,
    x.active_user_cnt,
    x.total_query_count,
    x.total_accepted_count,
    x.acceptance_rate,
    x.hours_saved,
    x.hours_saved_per_user,
    x.queries_per_user,
    ROUND(x.hours_saved * 1.0 / SUM(x.hours_saved) OVER (), 4) AS hours_share_pct,
    RANK() OVER (PARTITION BY x.dim_type ORDER BY x.acceptance_rate DESC) AS acceptance_rank_in_dim,
    NULL AS acceptance_rate_mom_change
FROM metrics x
UNION ALL
SELECT
    '月度趋势',
    '月度',
    mm.ym,
    NULL,
    mm.active_user_cnt,
    mm.total_query_count,
    mm.total_accepted_count,
    mm.acceptance_rate,
    mm.hours_saved,
    mm.hours_saved_per_user,
    NULL,
    NULL,
    NULL,
    ROUND(mm.acceptance_rate - LAG(mm.acceptance_rate) OVER (ORDER BY mm.ym), 4)
FROM monthly_metrics mm
ORDER BY scope, dim_type, dim_value;
