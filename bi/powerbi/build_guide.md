# Power BI 搭建指南

> 三条路，按省事程度排序。**推荐路线 A**。

---

## 路线 A：直接打开 PBIP 项目（推荐）

### A1. 打开

1. 启动 **Power BI Desktop**
2. 文件 → 打开 → 选 `bi/powerbi/ERP经营分析.pbip`
3. 等待模型加载（会提示加载 11 张表的 CSV 数据，约 10~30 秒）

### A2. 如果提示需要"信任"外部数据源

点「**加载**」→ 出现提示时选「**是**」（信任本地 CSV 文件）。

### A3. 如果报表页是空的 / 报 schema 错误

说明你的 Power BI Desktop 版本较旧（不支持 PBIR 2.0）或为 Store 版受限版本。
**改走路线 B**（5 分钟手工复现），或升级到最新版 Power BI Desktop。

### A4. 打开后你会看到什么

| 位置 | 内容 |
|------|------|
| **模型视图** | 11 张表（5 维 + 6 实）、15 条关系、30 个度量值 |
| 报表视图 | 2 个页面：`经营总览`、`库存与增长`；共 9 个视觉对象 |
| 度量值列表 | 营收、毛利、毛利率、客单价、营收同比/环比/YTD、缺货率、商机成单率、AI 辅助成单率、ROAS、CAC、AI 采纳率… |

### A5. 数据源路径说明

`model.tmdl` 里的 M 分区表达式写的是**绝对路径**，仓库里提交的是占位符（不把个人目录带进公开仓库）：

```
C:\\path\\to\\project-erp\\bi\\data\\xxx.csv
```

第一次打开前，二选一：

- 用 VS Code / 记事本打开 `model.tmdl` 做全局替换，把 `C:\\path\\to\\project-erp` 换成你本机的项目路径（注意 M 里反斜杠要双写）
- 或改用**相对路径**：`File.Contents("bi/data/xxx.csv")`（相对 Power BI 当前工作目录，可能不稳）

改完保存，回到 Power BI 选「**刷新**」。

---

## 路线 B：手工复现（PBIP 打不开时）

5 步做出完全一样的模型。

### B1. 导入数据

**获取数据 → 文件夹 →** 选到 `bi/data` 目录 → 左下角「**组合并并转换数据**」→ 打开 **高级编辑器**。

### B2. 粘贴 M 脚本

打开 `bi/powerbi/powerquery/erp_model.pq`，按 §0 的清单**逐个创建查询**：

| 顺序 | 查询名 | 来源 | 说明 |
|---|---|---|---|
| 1 | `p_DataFolder` | 参数 | 文本参数，值填 `bi/data` 的绝对路径 |
| 2 | `fn_ReadCSV` | 函数 | 统一处理 BOM、列名清洗、类型转换 |
| 3 | `stg_Date` | `dim_date.csv` | 日期维表 |
| 4 | `stg_Customer` | `dim_customer.csv` | |
| 5 | `stg_Employee` | `dim_employee.csv` | |
| 6 | `stg_Product` | `dim_product.csv` | |
| 7 | `stg_Sales` | `fact_sales_order_flat.csv` | **路线 A：裁掉冗余维度列** |
| 8 | `stg_Sales_Wide` | 同上 | **路线 B：保留全部展平列** |
| 9 | `stg_SalesItem` | `fact_sales_order_item_flat.csv` | |
| 10 | `stg_SalesItem_Wide` | 同上 | |
| 11 | `stg_Inventory` | `fact_inventory_snapshot_flat.csv` | |
| 12 | `stg_Inventory_Wide` | 同上 | |
| 13 | `stg_Lead` | `fact_lead_opportunity_flat.csv` | |
| 14 | `stg_Ticket` | `fact_customer_ticket_flat.csv` | |
| 15 | `stg_Marketing` | `fact_marketing_spend_flat.csv` | |
| 16 | `stg_AIUsage` | `fact_ai_usage_flat.csv` | |
| 17 | `dim_Date` | 由 `stg_Date` 派生 | 规范日期表（补齐缺失日期）+ 年月季度派生列 |
| 18 | `dim_RFM_Base` | 由 `stg_Sales` 派生 | RFM 计算底表 |
| 19 | `dim_RFM` | 由 `dim_RFM_Base` 派生 | RFM 分层结果 |

> **路线选择**：用**路线 A**（星型）做正经模型，维度属性靠关系取；
> 赶时间就用**路线 B**（宽表），导入即用、无需建关系。

### B3. 建关系

模型视图 → 拖拽连线，方向都是 **维度(1) → 事实(∞)**，交叉筛选方向设为**单向**：

| 维度表 | 维度列 | 事实表 | 事实列 |
|---|---|---|---|
| dim_date | full_date | fact_sales_order | order_date |
| dim_date | full_date | fact_inventory_snapshot | snapshot_date |
| dim_date | full_date | fact_lead_opportunity | created_date |
| dim_date | full_date | fact_customer_ticket | created_date |
| dim_date | full_date | fact_marketing_spend | date |
| dim_date | full_date | fact_ai_usage | date |
| dim_customer | customer_id | fact_sales_order | customer_id |
| dim_customer | customer_id | fact_lead_opportunity | customer_id |
| dim_customer | customer_id | fact_customer_ticket | customer_id |
| dim_employee | employee_id | fact_sales_order | employee_id |
| dim_employee | employee_id | fact_lead_opportunity | owner_employee_id |
| dim_employee | employee_id | fact_ai_usage | employee_id |
| dim_product | product_id | fact_sales_order_item | product_id |
| dim_product | product_id | fact_inventory_snapshot | product_id |
| fact_sales_order | order_id | fact_sales_order_item | order_id |

> **必须把 dim_date 标记为日期表**：
> 选中 dim_date → 表工具 → **标记为日期表** → 选 `full_date`。
> 不标记的话，同比/环比的时间智能函数会算错。

### B4. 加度量值

新建一个空表叫 `度量值`（输入表 → 改名），然后把 `dax/dax_measures.dax` 里的度量**逐条粘贴**进去。

该文件共 **52 个度量值，分 9 组**，每条都带「公式 / 业务含义 / 使用场景 / 考察点 / 期望基线」：

| 组 | 代表度量 |
|---|---|
| 核心经营 | 营收、毛利、毛利率、完成订单数、客单价、成交客户数 |
| 时间智能 | 营收同比、营收环比、营收 YTD、累计 YTD |
| 库存健康 | 库存金额、缺货 SKU 数、缺货率、在途库存、库存周转天数 |
| 客户价值 | RFM 分层相关度量、客单价对比、流失预警客户数 |
| 漏斗与赢率 | 商机数、商机金额、成单数、成单率、平均销售周期 |
| **AI 价值** | AI 辅助成单率、AI 采纳率、AI 节省工时、AI 处理工单占比、**AI 工时折算成本** |
| 营销效率 | 投放成本、归因收入、ROAS、CAC |
| 渠道与团队 | 按渠道/团队/区域的贡献与效率 |
| 质量与风险 | 折扣率、异常订单、库存对账差异 |

> 或者直接用 `model.tmdl` 里已内置的 **30 个度量值**（路线 A 打开 PBIP 时已经加载好了）。

### B5. 做报表页

参考 `ERP经营分析.Report/definition/report.json` 的 9 个视觉对象，或自己搭：

**页 1「经营总览」**
- 左上：折线图 —— 轴 `year_month`，值 `[营收]`，颜色 `[营收同比]`
- 右上：两个卡片 —— `[营收]`、`[毛利率]`
- 左下：表格 —— 行 `customer_tier` + `customer_industry`，值 `[营收]`
- 右下：表格 —— 行 `product_name` + `category`，值 `revenue_amount`

**页 2「库存与增长」**
- 左上：表格 —— 行 `warehouse` + `category`，值 `inventory_value` + `stock_gap`
- 右上：柱状图 —— 列 `stage`，值 `[商机数]`
- 左下：表格 —— 行 `channel`，值 `[投放成本]` `[归因收入]` `[ROAS]`
- 右下：柱状图 —— 列 `scenario`，值 `[AI 节省工时]` `[AI 采纳率]`

---

## 路线 C：只要度量值，不要模型

如果只是要展示「我会写 DAX」：

1. 打开 `dax/dax_measures.dax`
2. 新建报表 → 拖入任一 CSV
3. 新建表 `度量值`，逐条粘贴 DAX
4. 用字段、数值、卡片做出图

---

## 验证：建完之后怎么确认口径对

```bash
python bi/verify_baselines.py
```

会打印关键指标的期望值（如总营收、客单价、缺货率、AI 采纳率…）。
把 Power BI 里的数字和它逐项对上，**对上了就说明口径实现正确**。

更严格的验证：

```bash
python scripts/_compare_sql_dialects.py   # SQL 与 MySQL 的逐值一致性
python bi/powerbi/verify_pbip.py          # PBIP 结构与列名一致性
```

---

## 常见问题

| 现象 | 处理 |
|------|------|
| 列名变成 `﻿order_id`（带 BOM） | M 脚本里的 `fn_ReadCSV` 已处理；若手工导入记得加 `Table.ReplaceValue(..., "#(char)65279"&"order_id", "order_id", ...)` |
| 时间智能算出来是错的 | 没把 dim_date 标记为日期表 |
| 同比恒等于 0 | 维度列被筛选时没解除筛选，需要 `REMOVEFILTERS` |
| 关系连线报错「一对多已存在」 | 同一对表重复连线；或维度列有重复值需要先聚合 |
| Store 版打不开 PBIP | 走路线 B |
| CSV 改了但报表没变 | 右键数据源 → **刷新**；改的是 `bi/data/` 下的文件 |
