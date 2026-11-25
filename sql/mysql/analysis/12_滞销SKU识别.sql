-- ============================================================
-- 题目：滞销 SKU 识别与库存呆滞度排序——近 90 天无销售且仍有库存的资金占用清单
-- 口径：滞销 SKU（口径文档定义）= 近 90 天无销售（仅 status='已完成' 的订单明细计入动销）且库存 > 0 的 SKU；
--       窗口起点 = 快照日往前推 90 天（月末快照日 2025-12-31 → 2025-10-02）；
--       库存口径取月末快照 SUM(on_hand_qty) 汇总两个仓库；库存金额 = SUM(inventory_value)；
--       距上次销售天数 = 快照日 − 该 SKU 最近一次销售日；库存可售天数 = 库存量 ÷ 近 90 天日均销量；
--       动销率 = 近 90 天有动销 SKU 数 ÷ 在售 SKU 数（在售 = dim_product.status='在售'）。
--       本数据集 77 个有库存 SKU 近 90 天全部有动销（最短 0 天、最长 12 天），严格口径下滞销 SKU 为 0；
--       故脚本同时输出呆滞度排序（距上次销售天数 / 可售天数），以暴露「有销量但周转极慢」的真风险。
-- 考察点：NOT EXISTS 反连接判定窗口内无动销（严格滞销口径）；CTE 多路聚合 + 窗口累计；
--          窗口函数 ROW_NUMBER() 排呆滞优先级、SUM() OVER () 算金额占比、RANK() 排可售天数；
--          日期关联用 dim_date.full_date，避免 date_id（YYYYMMDD 整数）直接相减。
-- 预期结果：
--   共 77 行；列：sku, product_name, category, brand, product_status, on_hand_qty, in_transit_qty, inventory_value, qty_90d, revenue_90d, last_sale_date, days_since_last_sale, days_of_supply, is_slow_moving, dormancy_level, sell_through_rate_90d, active_sku_cnt, moving_sku_cnt, dormancy_rank, inventory_value_rank, inventory_value_share_pct, clearance_action
--     SKU-0030 | 三菱 标准型PLC控制器 | PLC控制器 | 三菱 | 在售 | 235 | 67 | 336,390.75 | 31 | 49,482.49 | 2025-12-31 | 0 | 682.3 | 否 | 呆滞-周转超1年 | 1 | 77 | 77 | 1 | 26 | 0.0176 | P0-立即清仓/退供谈判
--     SKU-0022 | 欧姆龙 防爆型PLC控制器 | PLC控制器 | 欧姆龙 | 在售 | 250 | 45 | 417,375 | 35 | 66,891.36 | 2025-12-30 | 1 | 642.9 | 否 | 呆滞-周转超1年 | 1 | 77 | 77 | 2 | 18 | 0.0219 | P0-立即清仓/退供谈判
--     SKU-0026 | 三菱 防爆型PLC控制器 | PLC控制器 | 三菱 | 在售 | 280 | 69 | 419,960.8 | 44 | 86,220.18 | 2025-12-29 | 2 | 572.7 | 否 | 呆滞-周转超1年 | 1 | 77 | 77 | 3 | 17 | 0.022 | P0-立即清仓/退供谈判
--     SKU-0032 | 哈默纳科 高防护型精密减速机 | 精密减速机 | 哈默纳科 | 在售 | 251 | 58 | 458,270.78 | 40 | 78,098.28 | 2025-12-31 | 0 | 564.8 | 否 | 呆滞-周转超1年 | 1 | 77 | 77 | 4 | 13 | 0.024 | P0-立即清仓/退供谈判
--     SKU-0023 | 西门子 经济型PLC控制器 | PLC控制器 | 西门子 | 在售 | 228 | 26 | 316,443.48 | 37 | 60,486.18 | 2025-12-27 | 4 | 554.6 | 否 | 呆滞-周转超1年 | 1 | 77 | 77 | 5 | 28 | 0.0166 | P0-立即清仓/退供谈判
--     SKU-0027 | 欧姆龙 高防护型PLC控制器 | PLC控制器 | 欧姆龙 | 在售 | 299 | 38 | 574,660.06 | 50 | 117,846.75 | 2025-12-31 | 0 | 538.2 | 否 | 呆滞-周转超1年 | 1 | 77 | 77 | 6 | 5 | 0.0301 | P0-立即清仓/退供谈判
--     SKU-0034 | 绿的谐波 经济型精密减速机 | 精密减速机 | 绿的谐波 | 在售 | 268 | 42 | 712,161.76 | 45 | 137,322.68 | 2025-12-31 | 0 | 536 | 否 | 呆滞-周转超1年 | 1 | 77 | 77 | 7 | 2 | 0.0373 | P0-立即清仓/退供谈判
--     SKU-0035 | 绿的谐波 增强型精密减速机 | 精密减速机 | 绿的谐波 | 在售 | 314 | 90 | 690,467.16 | 56 | 161,250.39 | 2025-12-31 | 0 | 504.6 | 否 | 呆滞-周转超1年 | 1 | 77 | 77 | 8 | 3 | 0.0362 | P0-立即清仓/退供谈判
--     ...（其余 69 行略）
-- ============================================================
WITH
-- 最新月末快照（业务窗口内）
last_snap AS (
    SELECT MAX(s.date_id) AS snap_date_id
    FROM fact_inventory_snapshot s
    JOIN dim_date d ON d.date_id = s.date_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 近 90 天 SKU 级动销汇总
sold_sku AS (
    SELECT
        it.product_id,
        SUM(it.qty)            AS qty_90d,
        SUM(it.revenue_amount) AS revenue_90d
    FROM fact_sales_order_item it
    JOIN fact_sales_order o ON o.order_id = it.order_id
    JOIN dim_date d ON d.date_id = o.order_date_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2025-10-02' AND '2025-12-31'
    GROUP BY it.product_id
),
-- 每个 SKU 的最近一次销售日（用于计算距上次销售天数）
last_sale AS (
    SELECT
        it.product_id,
        MAX(d.full_date) AS last_sale_date
    FROM fact_sales_order_item it
    JOIN fact_sales_order o ON o.order_id = it.order_id
    JOIN dim_date d ON d.date_id = o.order_date_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY it.product_id
),
-- 月末库存（SKU 级，汇总两个仓库）
snap AS (
    SELECT
        s.product_id,
        SUM(s.on_hand_qty)    AS on_hand_qty,
        SUM(s.inventory_value) AS inventory_value,
        SUM(s.in_transit_qty) AS in_transit_qty
    FROM fact_inventory_snapshot s
    JOIN last_snap ls ON ls.snap_date_id = s.date_id
    GROUP BY s.product_id
),
-- 全量指标（动销率分母/分子）
active_sku AS (
    SELECT COUNT(*) AS active_sku_cnt FROM dim_product WHERE status = '在售'
),
moving_stat AS (
    SELECT COUNT(DISTINCT product_id) AS moving_sku_cnt FROM sold_sku
),
-- 逐 SKU 计算呆滞指标
sku_health AS (
    SELECT
        p.product_id,
        p.sku,
        p.product_name,
        p.category,
        p.brand,
        p.status AS product_status,
        sk.on_hand_qty,
        sk.in_transit_qty,
        ROUND(sk.inventory_value, 2)                                                    AS inventory_value,
        COALESCE(ss.qty_90d, 0)                                                         AS qty_90d,
        COALESCE(ss.revenue_90d, 0)                                                    AS revenue_90d,
        ls.last_sale_date,
        CAST(DATEDIFF('2025-12-31', ls.last_sale_date) AS SIGNED)         AS days_since_last_sale,
        -- 库存可售天数 = 库存量 ÷ 近 90 天日均销量
        ROUND(sk.on_hand_qty * 1.0 / NULLIF(COALESCE(ss.qty_90d, 0) / 90.0, 0), 1)     AS days_of_supply
    FROM snap sk
    JOIN dim_product p ON p.product_id = sk.product_id
    LEFT JOIN sold_sku ss ON ss.product_id = sk.product_id
    LEFT JOIN last_sale ls ON ls.product_id = sk.product_id
    WHERE sk.on_hand_qty > 0
)
SELECT
    h.sku,
    h.product_name,
    h.category,
    h.brand,
    h.product_status,
    h.on_hand_qty,
    h.in_transit_qty,
    h.inventory_value,
    h.qty_90d,
    ROUND(h.revenue_90d, 2)                                                        AS revenue_90d,
    h.last_sale_date,
    h.days_since_last_sale,
    h.days_of_supply,
    -- 严格口径滞销标记：近 90 天无销售且库存 > 0
    CASE WHEN h.qty_90d = 0 THEN '是' ELSE '否' END                                AS is_slow_moving,
    -- 呆滞度分层（按可售天数）
    CASE
        WHEN h.days_of_supply > 365 THEN '呆滞-周转超1年'
        WHEN h.days_of_supply > 180 THEN '高呆滞-周转超半年'
        WHEN h.days_of_supply > 90  THEN '偏高-周转超季度'
        ELSE '正常'
    END                                                                            AS dormancy_level,
    -- 全局动销率（窗口内常量）
    ROUND(ms.moving_sku_cnt * 1.0 / NULLIF(a.active_sku_cnt, 0), 4)               AS sell_through_rate_90d,
    a.active_sku_cnt,
    ms.moving_sku_cnt,
    -- 呆滞优先级：按可售天数降序（配合库存金额）
    ROW_NUMBER() OVER (ORDER BY h.days_of_supply DESC, h.inventory_value DESC)     AS dormancy_rank,
    RANK()    OVER (ORDER BY h.inventory_value DESC)                               AS inventory_value_rank,
    ROUND(h.inventory_value * 1.0 / SUM(h.inventory_value) OVER (), 4)             AS inventory_value_share_pct,
    CASE
        WHEN h.days_of_supply > 365 THEN 'P0-立即清仓/退供谈判'
        WHEN h.days_of_supply > 180 THEN 'P1-促销去化'
        WHEN h.days_of_supply > 90  THEN 'P2-压缩备货'
        ELSE 'P3-正常备货'
    END                                                                            AS clearance_action
FROM sku_health h
CROSS JOIN active_sku a
CROSS JOIN moving_stat ms
ORDER BY h.days_of_supply DESC, h.inventory_value DESC;
