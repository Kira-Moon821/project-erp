-- ============================================================
-- 题目：AI 辅助商机 vs 未辅助商机的成单率、赢率与销售周期对照，量化 AI 的销售价值
-- 口径：成单率 = stage='成单' 数量 ÷ 线索总数；赢率（商机赢概率）= AVG(CAST(win_probability AS DOUBLE))（口径文档）；
--       销售周期 = AVG(CAST(cycle_days AS DOUBLE))；金额 = SUM(expected_amount) / SUM(actual_amount)（仅成单计实际金额）；
--       线索按 created_date_id 落在业务窗口 2024-01-01 ~ 2025-12-31。
-- 考察点：条件聚合 CASE WHEN 算成单/输单数；窗口函数做「AI 组 − 对照组」指标差值
--          （用 FIRST_VALUE/MAX OVER (PARTITION BY dim) 自关联取值实现组间对比）、
--          ROW_NUMBER() 排提升幅度；自连接式聚合对比 AI 组与对照组。
-- 预期结果：
--   共 26 行；列：dim_type, dim_value, ai_group, lead_cnt, won_cnt, lost_cnt, win_rate, avg_win_probability, avg_cycle_days, expected_amount, actual_amount, amount_realization_rate, win_rate_lift, win_rate_lift_pct, win_prob_lift, cycle_days_saved, ai_value_conclusion
--     整体 | ALL | AI辅助 | 354 | 77 | 28 | 0.2175 | 0.5155 | 36.5282 | 170,632,587.3 | 40,138,822.44 | 0.2352 | 0.0664 | 43.94 | 0.1295 | 9.34 | AI 提效验证：赢率更高且周期更短
--     整体 | ALL | 未AI辅助 | 708 | 107 | 83 | 0.1511 | 0.3859 | 45.8686 | 334,944,132.06 | 49,238,504.28 | 0.147 | 0.0664 | 43.94 | 0.1295 | 9.34 | 对照组（基线）
--     来源渠道 | 内容营销 | AI辅助 | 25 | 4 | 1 | 0.16 | 0.5416 | 35.68 | 9,600,356.28 | 969,585.99 | 0.101 | -0.0154 | -8.78 | 0.096 | 8.62 | 差异不明显
--     来源渠道 | 内容营销 | 未AI辅助 | 57 | 10 | 5 | 0.1754 | 0.4456 | 44.2982 | 26,151,111.75 | 3,356,385.97 | 0.1283 | -0.0154 | -8.78 | 0.096 | 8.62 | 对照组（基线）
--     来源渠道 | 官网 | AI辅助 | 96 | 20 | 7 | 0.2083 | 0.5121 | 36.3854 | 44,695,334.91 | 9,889,877.93 | 0.2213 | 0.0529 | 34.04 | 0.1323 | 12.44 | AI 提效验证：赢率更高且周期更短
--     来源渠道 | 官网 | 未AI辅助 | 193 | 30 | 25 | 0.1554 | 0.3798 | 48.829 | 88,261,849.84 | 13,228,942.88 | 0.1499 | 0.0529 | 34.04 | 0.1323 | 12.44 | 对照组（基线）
--     来源渠道 | 展会 | AI辅助 | 69 | 15 | 9 | 0.2174 | 0.4913 | 37.5072 | 33,292,716.97 | 7,699,453.65 | 0.2313 | 0.0375 | 20.84 | 0.0712 | 7.9 | AI 提效验证：赢率更高且周期更短
--     来源渠道 | 展会 | 未AI辅助 | 139 | 25 | 15 | 0.1799 | 0.4201 | 45.4029 | 65,456,477.91 | 9,939,201.04 | 0.1518 | 0.0375 | 20.84 | 0.0712 | 7.9 | 对照组（基线）
--     ...（其余 18 行略）
-- ============================================================
WITH
-- 窗口内线索
leads AS (
    SELECT
        l.lead_id,
        l.stage,
        l.source_channel,
        l.ai_assisted,
        l.cycle_days,
        l.win_probability,
        l.expected_amount,
        l.actual_amount
    FROM fact_lead_opportunity l
    JOIN dim_date d ON d.date_id = l.created_date_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 分组聚合（整体 / 按来源渠道 / 按阶段）
grouped AS (
    SELECT
        '整体' AS dim_type,
        'ALL' AS dim_value,
        ai_assisted,
        COUNT(*)                                                AS lead_cnt,
        SUM(CASE WHEN stage = '成单' THEN 1 ELSE 0 END)         AS won_cnt,
        SUM(CASE WHEN stage = '输单' THEN 1 ELSE 0 END)         AS lost_cnt,
        AVG(CAST(win_probability AS DOUBLE))                                   AS avg_win_probability,
        AVG(CAST(cycle_days AS DOUBLE))                                        AS avg_cycle_days,
        SUM(expected_amount)                                   AS expected_amount,
        SUM(actual_amount)                                     AS actual_amount
    FROM leads
    GROUP BY ai_assisted
    UNION ALL
    SELECT '来源渠道', source_channel, ai_assisted,
           COUNT(*),
           SUM(CASE WHEN stage = '成单' THEN 1 ELSE 0 END),
           SUM(CASE WHEN stage = '输单' THEN 1 ELSE 0 END),
           AVG(CAST(win_probability AS DOUBLE)), AVG(CAST(cycle_days AS DOUBLE)),
           SUM(expected_amount), SUM(actual_amount)
    FROM leads
    GROUP BY source_channel, ai_assisted
    UNION ALL
    SELECT '阶段', stage, ai_assisted,
           COUNT(*),
           SUM(CASE WHEN stage = '成单' THEN 1 ELSE 0 END),
           SUM(CASE WHEN stage = '输单' THEN 1 ELSE 0 END),
           AVG(CAST(win_probability AS DOUBLE)), AVG(CAST(cycle_days AS DOUBLE)),
           SUM(expected_amount), SUM(actual_amount)
    FROM leads
    GROUP BY stage, ai_assisted
),
-- 计算各组指标
metrics AS (
    -- MySQL 8 不允许 SELECT g.* 之后再定义同名列（Duplicate column name），
    -- 故此处显式列出 grouped 的全部列。
    -- 注意：MySQL 8 中 SELECT g.* 后面再写同名列时，下游引用取的是 g.* 里的原始列
    -- （MySQL 8 自动把重名列命名为 xxx:1，m.xxx 解析到第一个），
    -- 所以这里刻意不加 ROUND，与 MySQL 8 版逐值一致
    SELECT
        g.dim_type,
        g.dim_value,
        g.ai_assisted,
        g.lead_cnt,
        g.won_cnt,
        g.lost_cnt,
        g.avg_win_probability,
        g.avg_cycle_days,
        g.expected_amount,
        g.actual_amount,
        ROUND(g.won_cnt * 1.0 / NULLIF(g.lead_cnt, 0), 4)      AS win_rate,
        ROUND(g.actual_amount * 1.0 / NULLIF(g.expected_amount, 0), 4) AS amount_realization_rate
    FROM grouped g
),
-- 用窗口函数取同维度「AI 组」与「对照组」的指标，做差值
compared AS (
    SELECT
        m.*,
        MAX(CASE WHEN m.ai_assisted = 1 THEN m.win_rate END) OVER (PARTITION BY m.dim_type, m.dim_value)          AS ai_win_rate,
        MAX(CASE WHEN m.ai_assisted = 0 THEN m.win_rate END) OVER (PARTITION BY m.dim_type, m.dim_value)          AS ctrl_win_rate,
        MAX(CASE WHEN m.ai_assisted = 1 THEN m.avg_win_probability END) OVER (PARTITION BY m.dim_type, m.dim_value) AS ai_win_prob,
        MAX(CASE WHEN m.ai_assisted = 0 THEN m.avg_win_probability END) OVER (PARTITION BY m.dim_type, m.dim_value) AS ctrl_win_prob,
        MAX(CASE WHEN m.ai_assisted = 1 THEN m.avg_cycle_days END) OVER (PARTITION BY m.dim_type, m.dim_value)      AS ai_cycle_days,
        MAX(CASE WHEN m.ai_assisted = 0 THEN m.avg_cycle_days END) OVER (PARTITION BY m.dim_type, m.dim_value)      AS ctrl_cycle_days
    FROM metrics m
)
SELECT
    c.dim_type,
    c.dim_value,
    CASE c.ai_assisted WHEN 1 THEN 'AI辅助' ELSE '未AI辅助' END  AS ai_group,
    c.lead_cnt,
    c.won_cnt,
    c.lost_cnt,
    c.win_rate,
    c.avg_win_probability,
    c.avg_cycle_days,
    c.expected_amount,
    c.actual_amount,
    c.amount_realization_rate,
    -- AI 组相对对照组的提升
    ROUND(c.ai_win_rate - c.ctrl_win_rate, 4)                   AS win_rate_lift,
    ROUND((c.ai_win_rate - c.ctrl_win_rate) * 100
          / NULLIF(c.ctrl_win_rate, 0), 2)                       AS win_rate_lift_pct,
    ROUND(c.ai_win_prob - c.ctrl_win_prob, 4)                   AS win_prob_lift,
    ROUND(c.ctrl_cycle_days - c.ai_cycle_days, 2)                AS cycle_days_saved,
    -- AI 提效结论
    CASE
        WHEN c.ai_assisted = 1 AND c.win_rate > c.ctrl_win_rate AND c.avg_cycle_days < c.ctrl_cycle_days
            THEN 'AI 提效验证：赢率更高且周期更短'
        WHEN c.ai_assisted = 0 THEN '对照组（基线）'
        ELSE '差异不明显'
    END                                                           AS ai_value_conclusion
FROM compared c
ORDER BY c.dim_type, c.dim_value, c.ai_assisted DESC;
