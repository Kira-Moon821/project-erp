-- ============================================================
-- 题目：销售周期与赢率分析——各阶段/来源/销售员的周期长度与成单效率
-- 口径：销售周期 = fact_lead_opportunity.cycle_days（线索创建到关闭的自然日天数）；
--       赢率（成单率）= 成单数 ÷ 线索总数（口径文档：成单率 = stage='成单' 数量 ÷ 线索总数）；
--       商机赢概率 = AVG(win_probability)（口径文档：AI 辅助商机赢率口径）；
--       金额口径：expected_amount 为预期金额、actual_amount 为成单金额（仅成单有值）；
--       线索按 created_date_id 落在业务窗口 2024-01-01 ~ 2025-12-31。
-- 考察点：多层 GROUP BY 维度对比；窗口函数 RANK() OVER (PARTITION BY 维度 ORDER BY 赢率 DESC) 做组内排名、
--          AVG() OVER (PARTITION BY 维度) 做组内基准对比、NTILE(4) 做周期分位；
--          CASE WHEN 区分成单/输单的平均周期。
-- 预期结果：
--   共 13 行；列：dim_type, dim_value, lead_cnt, won_cnt, lost_cnt, win_rate, avg_win_probability, avg_cycle_days, avg_cycle_days_won, avg_cycle_days_lost, cycle_gap_won_minus_lost, expected_amount, actual_amount, amount_realization_rate, win_rate_rank_in_dim, cycle_speed_rank_in_dim, cycle_quartile_in_dim, cycle_vs_dim_avg
--     AI辅助 | AI辅助 | 354 | 77 | 28 | 0.2175 | 0.5155 | 36.53 | 37.3 | 39.29 | -1.99 | 170,632,587.3 | 40,138,822.44 | 0.2352 | 1 | 1 | 1 | -4.67
--     AI辅助 | 未AI辅助 | 708 | 107 | 83 | 0.1511 | 0.3859 | 45.87 | 45.44 | 47.9 | -2.46 | 334,944,132.06 | 49,238,504.28 | 0.147 | 2 | 2 | 2 | 4.67
--     来源渠道 | 电话外呼 | 93 | 19 | 14 | 0.2043 | 0.4233 | 41.24 | 41.42 | 52.14 | -10.72 | 44,825,063.01 | 10,943,122.58 | 0.2441 | 1 | 2 | 1 | -1.03
--     来源渠道 | 展会 | 208 | 40 | 24 | 0.1923 | 0.4437 | 42.78 | 43.85 | 43.83 | 0.02 | 98,749,194.88 | 17,638,654.69 | 0.1786 | 2 | 4 | 2 | 0.51
--     来源渠道 | 官网 | 289 | 50 | 32 | 0.173 | 0.4237 | 44.7 | 42.78 | 44.25 | -1.47 | 132,957,184.75 | 23,118,820.81 | 0.1739 | 3 | 6 | 4 | 2.43
--     来源渠道 | 内容营销 | 82 | 14 | 6 | 0.1707 | 0.4749 | 41.67 | 39.79 | 44.83 | -5.05 | 35,751,468.03 | 4,325,971.96 | 0.121 | 4 | 3 | 2 | -0.6
--     来源渠道 | 广告投放 | 158 | 25 | 13 | 0.1582 | 0.4316 | 40.17 | 42.76 | 43.23 | -0.47 | 75,571,894.39 | 11,996,207.88 | 0.1587 | 5 | 1 | 1 | -2.1
--     来源渠道 | 转介绍 | 232 | 36 | 22 | 0.1552 | 0.4072 | 43.06 | 39.67 | 47.59 | -7.92 | 117,721,914.3 | 21,354,548.8 | 0.1814 | 6 | 5 | 3 | 0.79
--     ...（其余 5 行略）
-- ============================================================
WITH
-- 窗口内线索 + 员工信息
leads AS (
    SELECT
        l.lead_id,
        l.stage,
        l.source_channel,
        l.ai_assisted,
        l.cycle_days,
        l.win_probability,
        l.expected_amount,
        l.actual_amount,
        l.loss_reason,
        e.employee_id,
        e.employee_name,
        e.team
    FROM fact_lead_opportunity l
    JOIN dim_date d ON d.date_id = l.created_date_id
    JOIN dim_employee e ON e.employee_id = l.owner_employee_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 三个维度纵向合并
unioned AS (
    SELECT '来源渠道' AS dim_type, source_channel AS dim_value, * FROM leads
    UNION ALL
    SELECT '销售团队', team, * FROM leads
    UNION ALL
    SELECT 'AI辅助', CASE ai_assisted WHEN 1 THEN 'AI辅助' ELSE '未AI辅助' END, * FROM leads
),
-- 维度汇总
dim_agg AS (
    SELECT
        u.dim_type,
        u.dim_value,
        COUNT(*)                                                     AS lead_cnt,
        SUM(CASE WHEN u.stage = '成单' THEN 1 ELSE 0 END)             AS won_cnt,
        SUM(CASE WHEN u.stage = '输单' THEN 1 ELSE 0 END)             AS lost_cnt,
        AVG(u.win_probability)                                       AS avg_win_probability,
        AVG(u.cycle_days)                                            AS avg_cycle_days,
        AVG(CASE WHEN u.stage = '成单' THEN u.cycle_days END)         AS avg_cycle_days_won,
        AVG(CASE WHEN u.stage = '输单' THEN u.cycle_days END)         AS avg_cycle_days_lost,
        SUM(u.expected_amount)                                       AS expected_amount,
        SUM(u.actual_amount)                                         AS actual_amount
    FROM unioned u
    GROUP BY u.dim_type, u.dim_value
),
-- 计算派生指标
metrics AS (
    SELECT
        a.*,
        ROUND(a.won_cnt * 1.0 / NULLIF(a.lead_cnt, 0), 4)            AS win_rate
    FROM dim_agg a
)
SELECT
    a.dim_type,
    a.dim_value,
    a.lead_cnt,
    a.won_cnt,
    a.lost_cnt,
    a.win_rate,
    ROUND(a.avg_win_probability, 4)                                 AS avg_win_probability,
    ROUND(a.avg_cycle_days, 2)                                      AS avg_cycle_days,
    ROUND(a.avg_cycle_days_won, 2)                                  AS avg_cycle_days_won,
    ROUND(a.avg_cycle_days_lost, 2)                                 AS avg_cycle_days_lost,
    ROUND(a.avg_cycle_days_won - a.avg_cycle_days_lost, 2)           AS cycle_gap_won_minus_lost,
    ROUND(a.expected_amount, 2)                                     AS expected_amount,
    ROUND(a.actual_amount, 2)                                       AS actual_amount,
    ROUND(a.actual_amount * 1.0 / NULLIF(a.expected_amount, 0), 4)   AS amount_realization_rate,
    -- 组内排名（按赢率）与周期分位
    RANK() OVER (PARTITION BY a.dim_type ORDER BY a.win_rate DESC)   AS win_rate_rank_in_dim,
    RANK() OVER (PARTITION BY a.dim_type ORDER BY a.avg_cycle_days ASC) AS cycle_speed_rank_in_dim,
    NTILE(4) OVER (PARTITION BY a.dim_type ORDER BY a.avg_cycle_days) AS cycle_quartile_in_dim,
    -- 与同维度平均周期的偏差
    ROUND(a.avg_cycle_days - AVG(a.avg_cycle_days) OVER (PARTITION BY a.dim_type), 2) AS cycle_vs_dim_avg
FROM metrics a
ORDER BY a.dim_type, a.win_rate DESC;
