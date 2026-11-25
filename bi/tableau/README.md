# Tableau 工作簿说明

> 主文件：**`bi/tableau/ERP经营分析.twbx`**（双击即可用 Tableau Public 打开）
> 明文版：`bi/tableau/ERP经营分析.twb`（便于 review / diff / 版本对比）

---

## 1. 打开方式

| 方式 | 文件 | 说明 |
|------|------|------|
| **推荐** | `ERP经营分析.twbx` | 打包文件，内含 `Data/` 下的 11 个 CSV，双击直接打开，**无需管路径** |
| 备用 | `ERP经营分析.twb` | 明文 XML，依赖外部 `bi/data/*.csv` 路径，路径不对会显示空字段 |

- 已用 **Tableau Public 2026.3**（`F:\tableau\bin\tabpublic.exe`）生成与校验
- Tableau Public 打开本地 `.twbx` 没问题；**保存**时会提示发布到 Public，选「保存到本地」即可

> ⚠️ **BOM 陷阱（已处理）**
> `bi/data/*.csv` 是 UTF-8 **with BOM**（为了让 Excel 双击不乱码）。
> Tableau 的 textscan 连接读 BOM 时可能把 `﻿order_id` 粘进首列名，与工作簿里声明的
> `[order_id]` 对不上 → 字段全空。**因此 twbx 内统一放无 BOM 的 UTF-8 副本**，
> 由 `build_twb.py` 在打包时自动转换。

---

## 2. 工作簿内容

### 2.1 数据源（11 个）

| 数据源 | 行数量级 | 说明 |
|---|---:|---|
| `dim_date` | 822 | 日期维表 |
| `dim_customer` | 60 | 客户维表 |
| `dim_employee` | 18 | 员工维表 |
| `dim_product` | 80 | 商品维表 |
| `fact_sales_order_flat` | ~5.7k | 订单头 |
| `fact_sales_order_item_flat` | ~15.2k | 订单行 |
| `fact_inventory_snapshot_flat` | ~3.8k | 库存快照 |
| `fact_lead_opportunity_flat` | ~1.0k | 商机漏斗 |
| `fact_customer_ticket_flat` | ~765 | 客服工单 |
| `fact_marketing_spend_flat` | ~144 | 营销投放 |
| `fact_ai_usage_flat` | ~1.2k | AI 使用记录 |

### 2.2 计算字段（32 个）

完整清单与公式见 **`calcs.md`**（由 `gen_calcs_doc.py` 从 twb 自动提取，保证一致）。

四大类：
- **销售口径**：营收(已完成)、毛利(已完成)、毛利率、完成订单数、客单价、平均折扣率、营收同比、成交客户数
- **商品分析**：商品营收、商品毛利、累计占比、销量
- **库存分析**：库存金额、缺货SKU数、缺货率、库存周转率(期末)
- **增长与 AI**：商机数、商机金额、成单数、成单率、AI辅助成单率、平均销售周期、投放成本、归因收入、ROAS、CAC、AI采纳率、AI节省工时、AI调用次数、AI处理工单占比、平均解决时长、平均满意度

### 2.3 工作表（10 个）

| # | 工作表 | 数据源 | 图形 | 看什么 |
|---|---|---|---|---|
| 1 | **销售月度趋势** | fact_sales_order_flat | 折线 | 月度营收 + 同比（同比用 `LOOKUP(..., -12)`，**不是** Y 轴第二条线） |
| 2 | **渠道销售结构** | fact_sales_order_flat | 柱状 | 各订单渠道的营收与毛利对比 |
| 3 | **客户层级贡献** | fact_sales_order_flat | 柱状 | A/B/C 层级 × 行业的营收贡献 |
| 4 | **商品帕累托** | fact_sales_order_item_flat | 柱状 | 商品营收 + 累计占比（80/20 定位核心 SKU） |
| 5 | **客户RFM散点** | fact_sales_order_flat | 圆点 | 横轴订单数、纵轴营收、大小=营收、颜色=层级 |
| 6 | **商机漏斗** | fact_lead_opportunity_flat | 柱状 | 各阶段商机数 + 成单率，颜色区分 AI 辅助 |
| 7 | **库存健康** | fact_inventory_snapshot_flat | 方块 | 仓库 × 品类 的库存金额与缺货率 |
| 8 | **渠道投放效率** | fact_marketing_spend_flat | 圆点 | 渠道 ROAS，气泡大小=投放成本，标签=CAC |
| 9 | **AI使用效能** | fact_ai_usage_flat | 柱状 | 各 AI 场景节省工时，颜色=采纳率 |
| 10 | **工单与AI承接** | fact_customer_ticket_flat | 柱状 | 工单类型的解决时长，AI 承接 vs 人工 |

### 2.4 仪表板（3 个）

| 仪表板 | 布局 | 包含工作表 |
|---|---|---|
| **经营总览** | 2×2 | 销售月度趋势（上整行）、客户层级贡献（左下）、商品帕累托（右下） |
| **销售与客户** | 2×2 | 渠道销售结构、商机漏斗、客户RFM散点、商品帕累托 |
| **库存与增长** | 2×2 | 库存健康、渠道投放效率、AI使用效能、工单与AI承接 |

---

## 3. 口径说明（与 SQL / Excel / Power BI 完全一致）

| 指标 | Tableau 计算字段写法 | 关键点 |
|---|---|---|
| 营收 | `SUM(IF [order_status]="已完成" AND [is_return]=0 THEN [net_amount] END)` | 双重过滤：已完成 + 非退货 |
| 毛利率 | `SUM(...gross_profit END) / SUM(...net_amount END)` | 先聚合分子分母再相除 |
| 完成订单数 | `COUNTD(IF [order_status]="已完成" AND [is_return]=0 THEN [order_id] END)` | 用 COUNTD 不用 COUNT |
| 营收同比 | `SUM(...) / LOOKUP(SUM(...), -12)` | LOOKUP 依赖视图内 24 个月连续，**别加筛选把月份切碎** |
| 帕累托累计占比 | `RUNNING_SUM(SUM([revenue_amount])) / TOTAL(SUM([revenue_amount]))` | 表计算 |
| 缺货率 | `COUNTD(IF [stock_gap]>0 THEN [product_id] END) / COUNTD([product_id])` | |
| AI 辅助成单率 | `COUNTD(IF [stage]="成单" AND [ai_assisted]=1 THEN [lead_id] END) / COUNTD(IF [ai_assisted]=1 THEN [lead_id] END)` | 分母是 AI 组，不是全体 |
| ROAS | `SUM([revenue_attributed]) / SUM([cost_amount])` | 不要直接对行级 `roas` 列求和 |

---

## 4. 想改成星型模型？

当前工作簿用的是**展平事实表**（CSV 已把维度属性冗余进行里），稳定易用但维度不可复用。
改成星型的步骤：

1. 在 Power BI 里用 `bi/powerbi/powerquery/erp_model.pq` 的 M 脚本生成一份裁剪版（路线 A），
   或直接在 Tableau 里手动建关系
2. Tableau 中建立关系的方式：
   - 双击数据源 → **关系** 选项卡 → 拖 `dim_customer.customer_id` 到 `fact_sales_order.customer_id`
   - 勾选 **不用于引用** 的表设为主表（事实表），引用关系设为「多对多」或「一对多（不强制）」
3. 改完后原来直接用 `[customer_tier]` 的地方会失效，需要改成 `SUM([customer_tier])` 之类 —— **实际不推荐这么做**

> **实务建议**：本数据集的维度属性在事实表里是**冗余但一致**的（已由
> `bi/verify_baselines.py` 验证「事实表展平属性 vs 维度表」不一致数为 0），
> 所以单表路线在数值上完全等价，只是工程规范性略低。

---

## 5. 重新生成与校验

```bash
python bi/tableau/build_twb.py        # 生成 .twb 与 .twbx
python bi/tableau/verify_twb.py       # 结构自检（XML / 字段引用 / 列名 / BOM）
python bi/tableau/gen_calcs_doc.py    # 重新生成 calcs.md
```

`verify_twb.py` 检查 6 项：

1. twb 的 XML 是否良构
2. 每个工作表引用的数据源 id 是否存在
3. 每个 rows/cols/encodings 引用的字段实例是否在 `datasource-dependencies` 里声明过
4. 每个计算字段公式引用的原始列是否真的存在于该数据源
5. twbx 内是否含全部 CSV，且**无 BOM**
6. `metadata-records` 的列名与 CSV 实际表头是否完全一致

> 第 3 项在开发中真的抓到过一个 bug：字段引用被写成了双层方括号
> `[[none:xxx:nk]]`，Tableau 会显示空列 —— 这就是写校验脚本的意义。
