-- ============================================================
-- 题目：缺货与低于安全库存 SKU 诊断，输出补货优先级清单
-- 口径：缺货率 = on_hand_qty < safety_stock 的 SKU 行数 ÷ SKU 总行数（口径文档定义）；
--       断货 = on_hand_qty ≤ 0；在途量 = in_transit_qty（可覆盖缺口的缓冲）；
--       缺口量 = MAX(safety_stock − on_hand_qty, 0)；缺货金额 = 缺口量 × unit_cost；
--       快照日取业务窗口内最后一个月末（2025-12-31），库存指标不受订单状态影响。
-- 考察点：条件聚合 COUNT(CASE WHEN ...) 算缺货率与断货数；SUM(CASE WHEN ...) 汇总缺口；
--          窗口函数 ROW_NUMBER() OVER (ORDER BY 缺口金额 DESC) 生成补货优先级、
--          SUM() OVER () 计算缺口金额占比；LEFT JOIN 保证零库存 SKU 也出现在结果里。
-- 预期结果：
--   共 8 行；列：sku, product_name, category, brand, product_status, warehouse, on_hand_qty, safety_stock, in_transit_qty, gap_qty, gap_amount, inventory_value, shortage_type, replenish_priority, gap_amount_share_pct, shortage_rate, stockout_rate, total_gap_qty, total_gap_amount, total_in_transit_qty, shortage_sku_list, replenish_action
--     SKU-0041 | 施耐德 紧凑型变频器 | 变频器 | 施耐德 | 在售 | 华东仓 | 0 | 26 | 4 | 26 | 21,965.84 | 0 | 断货 | 1 | 0.4584 | 0.05 | 0.0437 | 74 | 47,919.84 | 4599 | SKU-0041, SKU-0043, SKU-0052, SKU-0052, SKU-0071, SKU-0071, SKU-0078, SKU-0078 | P0-断货且无在途覆盖
--     SKU-0043 | 英威腾 经济型变频器 | 变频器 | 英威腾 | 在售 | 华东仓 | 3 | 21 | 42 | 18 | 18,331.2 | 3,055.2 | 低于安全库存 | 2 | 0.3825 | 0.05 | 0.0437 | 74 | 47,919.84 | 4599 | SKU-0041, SKU-0043, SKU-0052, SKU-0052, SKU-0071, SKU-0071, SKU-0078, SKU-0078 | P3-在途可覆盖
--     SKU-0078 | 明纬 高精度型电源模块 | 电源模块 | 明纬 | 停产 | 华东仓 | 0 | 5 | 0 | 5 | 1,488.35 | 0 | 断货 | 3 | 0.0311 | 0.05 | 0.0437 | 74 | 47,919.84 | 4599 | SKU-0041, SKU-0043, SKU-0052, SKU-0052, SKU-0071, SKU-0071, SKU-0078, SKU-0078 | P0-断货且无在途覆盖
--     SKU-0078 | 明纬 高精度型电源模块 | 电源模块 | 明纬 | 停产 | 西南仓 | 0 | 5 | 27 | 5 | 1,488.35 | 0 | 断货 | 4 | 0.0311 | 0.05 | 0.0437 | 74 | 47,919.84 | 4599 | SKU-0041, SKU-0043, SKU-0052, SKU-0052, SKU-0071, SKU-0071, SKU-0078, SKU-0078 | P1-断货待补
--     SKU-0071 | 欧陆科 紧凑型电源模块 | 电源模块 | 欧陆科 | 停产 | 华东仓 | 0 | 5 | 52 | 5 | 1,457.8 | 0 | 断货 | 5 | 0.0304 | 0.05 | 0.0437 | 74 | 47,919.84 | 4599 | SKU-0041, SKU-0043, SKU-0052, SKU-0052, SKU-0071, SKU-0071, SKU-0078, SKU-0078 | P1-断货待补
--     SKU-0071 | 欧陆科 紧凑型电源模块 | 电源模块 | 欧陆科 | 停产 | 西南仓 | 0 | 5 | 32 | 5 | 1,457.8 | 0 | 断货 | 6 | 0.0304 | 0.05 | 0.0437 | 74 | 47,919.84 | 4599 | SKU-0041, SKU-0043, SKU-0052, SKU-0052, SKU-0071, SKU-0071, SKU-0078, SKU-0078 | P1-断货待补
--     SKU-0052 | SMC 高精度型气动元件 | 气动元件 | SMC | 停产 | 华东仓 | 0 | 5 | 27 | 5 | 865.25 | 0 | 断货 | 7 | 0.0181 | 0.05 | 0.0437 | 74 | 47,919.84 | 4599 | SKU-0041, SKU-0043, SKU-0052, SKU-0052, SKU-0071, SKU-0071, SKU-0078, SKU-0078 | P1-断货待补
--     SKU-0052 | SMC 高精度型气动元件 | 气动元件 | SMC | 停产 | 西南仓 | 0 | 5 | 11 | 5 | 865.25 | 0 | 断货 | 8 | 0.0181 | 0.05 | 0.0437 | 74 | 47,919.84 | 4599 | SKU-0041, SKU-0043, SKU-0052, SKU-0052, SKU-0071, SKU-0071, SKU-0078, SKU-0078 | P1-断货待补
-- ============================================================
WITH
-- 最新月末快照（限定业务窗口内）
last_snap AS (
    SELECT MAX(s.date_id) AS snap_date_id
    FROM fact_inventory_snapshot s
    JOIN dim_date d ON d.date_id = s.date_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 快照明细 + 缺口计算
snap_detail AS (
    SELECT
        s.date_id,
        s.product_id,
        s.warehouse,
        s.on_hand_qty,
        s.safety_stock,
        s.in_transit_qty,
        s.unit_cost,
        s.inventory_value,
        p.sku,
        p.product_name,
        p.category,
        p.brand,
        p.status AS product_status,
        MAX(s.safety_stock - s.on_hand_qty, 0)                  AS gap_qty,
        MAX(s.safety_stock - s.on_hand_qty, 0) * s.unit_cost     AS gap_amount
    FROM fact_inventory_snapshot s
    JOIN last_snap ls ON ls.snap_date_id = s.date_id
    JOIN dim_product p ON p.product_id = s.product_id
),
-- 全量快照汇总行（分母）
snap_total AS (
    SELECT
        COUNT(*)                                    AS sku_row_cnt,
        COUNT(DISTINCT product_id)                  AS product_cnt,
        SUM(CASE WHEN on_hand_qty < safety_stock THEN 1 ELSE 0 END) AS shortage_row_cnt,
        SUM(CASE WHEN on_hand_qty <= 0 THEN 1 ELSE 0 END)          AS stockout_row_cnt,
        SUM(gap_qty)                                AS total_gap_qty,
        SUM(gap_amount)                             AS total_gap_amount,
        SUM(in_transit_qty)                         AS total_in_transit_qty,
        -- 字符串聚合：按仓库列出缺货 SKU 清单
        group_concat(CASE WHEN on_hand_qty < safety_stock THEN sku END, ', ') AS shortage_sku_list
    FROM snap_detail
)
SELECT
    sd.sku,
    sd.product_name,
    sd.category,
    sd.brand,
    sd.product_status,
    sd.warehouse,
    sd.on_hand_qty,
    sd.safety_stock,
    sd.in_transit_qty,
    sd.gap_qty,
    ROUND(sd.gap_amount, 2)                                        AS gap_amount,
    ROUND(sd.inventory_value, 2)                                   AS inventory_value,
    CASE WHEN sd.on_hand_qty <= 0 THEN '断货' ELSE '低于安全库存' END AS shortage_type,
    -- 补货优先级：按缺口金额降序
    ROW_NUMBER() OVER (ORDER BY sd.gap_amount DESC, sd.gap_qty DESC) AS replenish_priority,
    -- 该 SKU 占全量缺口金额的比重
    ROUND(sd.gap_amount * 1.0 / NULLIF(t.total_gap_amount, 0), 4)  AS gap_amount_share_pct,
    -- 整体缺货指标（窗口内常量）
    ROUND(t.shortage_row_cnt * 1.0 / NULLIF(t.sku_row_cnt, 0), 4)  AS shortage_rate,
    ROUND(t.stockout_row_cnt * 1.0 / NULLIF(t.sku_row_cnt, 0), 4)   AS stockout_rate,
    t.total_gap_qty,
    ROUND(t.total_gap_amount, 2)                                    AS total_gap_amount,
    t.total_in_transit_qty,
    t.shortage_sku_list,
    CASE
        WHEN sd.on_hand_qty <= 0 AND sd.in_transit_qty < sd.gap_qty THEN 'P0-断货且无在途覆盖'
        WHEN sd.on_hand_qty <= 0                                  THEN 'P1-断货待补'
        WHEN sd.in_transit_qty < sd.gap_qty                       THEN 'P2-低于安全库存且在途不足'
        ELSE 'P3-在途可覆盖'
    END                                                            AS replenish_action
FROM snap_detail sd
CROSS JOIN snap_total t
WHERE sd.on_hand_qty < sd.safety_stock
ORDER BY sd.gap_amount DESC, sd.gap_qty DESC;
