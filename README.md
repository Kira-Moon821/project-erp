# ERP 经营分析实验室 · Analytics Lab

> 面向 **数据分析岗位** 的可本地复现作品集：同一个 ERP 业务数据集，
> 用 **SQL / Excel 数据透视表 / Power BI / Tableau** 四个工具各做一遍，
> 并把 **AI 产品销售** 的思考落成可执行的方法论与取数脚本。

**核心主张：四个工具共用一套口径，数字互相印证。**
这不是四个独立 demo，而是一个数据仓库 + 一层 BI 消费层 + 一套自动化校验。

---

## 0. 30 秒上手

```bash
cd erp-analytics-lab
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
python scripts/seed_db.py --reset                    # 建库 + 灌 24 个月确定性数据
uvicorn app.main:app --reload --port 8000            # 起服务
```

打开 <http://127.0.0.1:8000> → 用 `analyst / Analyst@123456` 登录 → 看经营看板。

> **Windows 最省事的方式：双击项目根目录的 `启动网站.bat`。**
> 它会自动检测服务是否在跑（在跑就直接开 Edge，没跑就先起服务再开 Edge），
> 不需要记命令、也不需要关心当前终端在哪个子目录。
> 注意：必须在**项目根目录**执行脚本；如果在 `web\` 等子目录里，请先 `cd ..` 回到 `erp-analytics-lab`。
> 一定要用命令行启动时，进入项目根目录后执行：`.\启动网站.bat`（路径随你的克隆位置而定，不要照抄别人的绝对路径）。
>
> **关于 Python 解释器**：脚本会自己找"装了依赖的那个 Python"，顺序是 `项目根目录\.venv` → PATH 里的每个 `python` → WorkBuddy 内置解释器 → 官方安装目录，每个候选都用 `-c "import uvicorn"` 实测。所以机器上同时装了 Anaconda 也不会跑错（`No module named uvicorn` 就是这个原因）。`scripts/serve.cmd` 承载真正的启动命令，崩溃时窗口会停住并显示报错。

一键完成（Windows PowerShell）：

```powershell
.\scripts\setup.ps1     # 建虚拟环境 + 装依赖 + 建库 + 导出 CSV / Excel 工作簿
.\scripts\run.ps1       # 起服务
```

---

## 0.1 文档导航

| 文档 | 讲什么 |
|---|---|
| [docs/技术实现文档.md](docs/技术实现文档.md) | 分层构建全过程：每层做法 + 为什么这么做 + 知识点 + 行业黑话（含第 11 节 Windows 一键启动脚本原理与排错） |
| [docs/数据字典与业务口径.md](docs/数据字典与业务口径.md) | 表 / 字段 / 指标口径的唯一定义，四个工具都以此为准 |
| [docs/竞品分析.md](docs/竞品分析.md) | 主流 ERP 与 BI 产品结构横向对比 + 本项目优劣势、能力对账、优化路线 |
| [docs/AI产品销售思考.md](docs/AI产品销售思考.md) | AI 产品销售方法论：客户画像、价值主张、定价、POC、异议处理 |
| [docs/AI产品销售思考_取数脚本.sql](docs/AI产品销售思考_取数脚本.sql) | 上述思考用到的取数 SQL，可直接跑出支撑数字 |

---

## 1. 这个项目在解决什么问题

一个 B2B 工业自动化零部件经销商，24 个月经营数据（2024-01-01 ~ 2025-12-31）。
数据里有真实业务该有的脏东西：

- 订单有 **已完成 / 处理中 / 已取消** 三种状态，还有**退货单**
- 库存要能对账：**期初 + 采购入库 − 销售出库 + 退货入库 − 报废 = 月末快照**
- 线索漏斗有阶段流失，AI 辅助与否的商机表现要能对照
- 客服工单分 AI 承接与人工处理
- 营销投放要能算 CAC / ROAS
- 销售在用 AI 助手，有调用量、采纳率、节省工时

所以本项目的技术含量不在"画图"，在**把口径钉死，让四个工具算出同一个数**。

---

## 2. 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Pydantic v2 | 分层：routes → services → repositories → models |
| 数据库 | SQLite（默认，零配置）/ MySQL 8（Docker 或本机） | 同一套 ORM 自动导出两套方言 DDL |
| 鉴权 | JWT 短访问令牌(15min) + 服务端刷新令牌(7d，轮换即吊销) | 口令 PBKDF2-HMAC-SHA256（纯标准库，无编译依赖） |
| 权限 | RBAC：`admin / analyst / sales / viewer` | 权限集合 `{read, write, analytics, admin}` |
| 前端 | 零构建 vanilla JS + 手写 SVG 图表 | 不引入框架，`python -m http.server` 级依赖 |
| BI | Power BI Desktop（PBIP 项目）/ Tableau Public（.twb + .twbx） | 真实工程文件，不是说明书 |
| 表格 | openpyxl 生成工作簿 + VBA 宏一键生成真透视表 | 三层结构：明细 / 公式预聚合 / 交互透视 |

---

## 3. 目录结构

```
erp-analytics-lab/
├── app/
│   ├── api/routes/          # auth / dashboard / erp —— 控制器
│   ├── services/            # auth_service / order_service / insight_service
│   ├── repositories/        # analytics_repo（分析查询）/ erp_repo（基础 CRUD）
│   ├── db/                  # models.py（5 维 + 9 实 + 2 系统表）、seed.py、session.py
│   ├── core/                # config / errors / logging / security
│   └── schemas/             # Pydantic 出入参模型
├── web/                     # 零构建看板（登录 / 总览 / 销售 / 库存 / 漏斗与AI / 产品 / 客户 / 订单）
├── sql/
│   ├── sqlite/analysis/     # 20 个分析脚本（SQLite 方言）
│   ├── mysql/analysis/      # 20 个分析脚本（MySQL 8 方言）
│   └── schema.sql           # DDL
├── bi/
│   ├── data/                # 11 个 utf-8-sig CSV（BI 与 Excel 的共同数据源）
│   ├── powerbi/             # ★ PBIP 项目 + Power Query M + DAX + 建模说明
│   └── tableau/             # ★ .twb / .twbx 工作簿 + 校验脚本
├── excel/
│   ├── ERP经营分析_数据源.xlsx   # 18 个工作表
│   ├── pivot_macro.bas       # 一键生成 8 个真透视表的 VBA 宏
│   └── pivot_guide.md        # 透视表操作指南 + 口径对照 + 面试话术
├── scripts/                 # seed / export_schema / export_bi_csv / build_pivot / setup / run
├── docs/
│   ├── 数据字典与业务口径.md     # ★ 唯一口径来源，所有工具以此为准
│   ├── AI产品销售思考.md         # ★ AI 产品销售方法论
│   ├── 技术实现文档.md           # ★ 分层构建：每层做法 + 知识点 + 行业黑话
│   └── screenshots/              # 看板实拍截图（7 个视图）
├── tests/test_api.py        # pytest 冒烟（含 RBAC / 库存校验 / 刷新令牌轮换 / 库存对账）
├── docker-compose.yml       # MySQL 8.4 + utf8mb4 + schema.sql 初始化
└── README.md
```

---

## 3.5 看板实拍

零构建 vanilla JS + 手写图表，7 个视图：

| 视图 | 内容 |
|---|---|
| **经营总览** | 8 个 KPI 卡（含同比）· 营收趋势 · **带证据 SQL 的自动洞察** · 销售漏斗 · AI 采纳率与节省工时 |
| **销售分析** | 月度趋势明细表 · Top 客户 / Top 商品 · 按行业/区域/渠道/客户层级四维拆解 |
| **库存健康** | 库存金额 · 缺货 SKU · 周转趋势 |
| **漏斗与 AI 价值** | 线索→成单漏斗（逐级转化 + 周期）· 渠道 CAC/ROAS 与投放建议 · **AI 辅助 vs 对照组** · **AI 工单 vs 人工** |
| **产品 / 客户 / 订单主数据** | 可搜索分页列表，支持下单（走库存校验与收发存流水） |

截图见 `docs/screenshots/`。其中「轻量洞察」区块的每一条都带**可执行的证据 SQL**，
说明结论不是拍脑袋写的 —— 复制进数据库就能验证。

---

## 4. 四件套：同一份数据，四种工具

### 4.1 SQL — `sql/`

20 个分析脚本，SQLite 与 MySQL 8 各一套等价实现。覆盖：

| 类别 | 脚本 |
|---|---|
| 销售 | 月度趋势与同比环比、商品帕累托与 ABC、商品毛利与折扣率、客户分层与客单价、区域行业渠道对比 |
| 客户 | RFM 分层、流失预警 |
| 库存 | 周转天数与金额趋势、缺货与低于安全库存 SKU、滞销 SKU 识别、**库存收发存对账** |
| 供应链 | 采购提前期与供应商表现 |
| 运营 | 交付时效与及时率 |
| 增长 | 线索漏斗逐级转化率、销售周期与赢率、**AI 辅助 vs 未辅助商机对照**、工单 AI 处理 vs 人工、营销 CAC/ROAS、AI 助手采纳率与节省工时、销量预测基线（移动平均与同比） |

用到的分析手法：CTE、窗口函数（`RANK` / `LAG` / `SUM OVER`）、条件聚合、日期序列补齐、连续月份对齐同比。

**跨方言验证（本项目最有说服力的一环）**

MySQL 8 版由 SQLite 版**自动转换**生成（`scripts/sqlite_to_mysql.py`），保证逻辑等价；
再把两个版本分别跑在真机上**逐行逐列比对**（`scripts/_compare_sql_dialects.py`）：

| 结果 | 说明 |
|---|---|
| **15 个脚本逐值完全一致** | 列名、行数、每一个单元格都相同 |
| **5 个脚本末位精度差异** | 共 13 处，全部是引擎数值语义差异，**不是口径差异** |

差异根因已逐条定位并写进 `docs/数据字典与业务口径.md` §6.2：

- MySQL `div_precision_increment` 默认 4 → `DECIMAL` 除法结果先被截断到 4 位小数
- MySQL `AVG(DECIMAL)` 的结果 scale = 4，SQLite `AVG(REAL)` 是完整浮点精度
- 两库 `SUM(DOUBLE)` 的浮点累加顺序不同，在 `.x5` 舍入边界上差 1 个末位单位

比对过程中还抓到并修了 **3 处真实的确定性 bug**（`NTILE` 并列分位、两个 `ORDER BY` 缺唯一 tiebreaker）——
这正是「同数据同口径」需要自动化比对才能发现的东西。

```bash
python scripts/sqlite_to_mysql.py        # SQLite 源 → MySQL 8 版
python scripts/_run_sql_analysis.py --mysql --fill   # MySQL 上执行 + 回填
python scripts/_compare_sql_dialects.py  # 跨方言逐值比对
python scripts/_gen_sql_verification.py  # 生成 sql/_验证结果.md
```

验证汇总见 **`sql/_验证结果.md`**（自动生成，数据全部来自真实执行）。
本机已装 MySQL Server 8.0，验证方式见 `scripts/_verify_mysql_instance.md`。

### 4.2 Excel — `excel/`

`ERP经营分析_数据源.xlsx`，18 个工作表，**三层分析结构**：

1. **明细层** —— 订单明细表、商品销售明细、库存快照、线索商机、客服工单、营销投放、AI 使用记录 + 4 张维度表
2. **公式预聚合层** —— `透视预分析` 页用 `SUMIFS` / `COUNTIFS` 复刻透视表结果
3. **静态预聚合层** —— `透视结果_品类营收 / _客户结构 / _月度趋势 / _漏斗与AI`
4. **交互透视层** —— 运行 `pivot_macro.bas` 一键生成 8 个**真·数据透视表**（含计算字段毛利率、AI 采纳率、AI 辅助占比）

> 本机 Office 处于许可过期（只读）模式，无法在交付前自动生成 PivotTable 对象，
> 因此预置宏 + 静态页 + 公式页三重保障。详见 `excel/pivot_guide.md`。

### 4.3 Power BI — `bi/powerbi/`

**`ERP经营分析.pbip` 是一个真正的 Power BI 项目**（不是说明书）：

```
bi/powerbi/
├── ERP经营分析.pbip                    ← 双击这个用 Power BI Desktop 打开
├── ERP经营分析.SemanticModel/
│   ├── definition.pbism
│   └── definition/model.tmdl            ← 星型模型：11 表 / 30 度量值 / 15 关系
└── ERP经营分析.Report/
    ├── definition.pbir
    └── definition/report.json           ← 2 个报表页 / 9 个视觉对象
```

- **模型**：星型（5 维度 + 6 事实），TMDL 纯文本可读可审
- **度量值 30 个**：营收、毛利、毛利率、客单价、营收同比/环比/YTD、库存金额、缺货率、缺货 SKU 数、商机数、成单率、AI 辅助成单率、平均销售周期、ROAS、CAC、AI 采纳率、AI 节省工时、AI 处理工单占比 …
- **时间智能**：同比用 `DATEADD(dim_date[full_date], -1, YEAR)`，环比用 `MONTH`
- **兜底方案**：`powerquery/erp_model.pq`（Power Query M）+ `dax/dax_measures.dax`（可直接粘贴的 DAX）+ `model.md`（建模说明），即使 PBIP 打不开也能 5 分钟手工复现

```bash
python bi/powerbi/build_pbip.py && python bi/powerbi/verify_pbip.py   # 生成 + 结构自检
```

### 4.4 Tableau — `bi/tableau/`

**`ERP经营分析.twbx` 是可双击打开的 Tableau 工作簿**（Tableau Public 2026.3 实测可用）：

- **11 个数据源**（CSV textscan 连接，twbx 内已放无 BOM 副本避免首列名错位）
- **32 个计算字段**：营收(已完成)、毛利、毛利率、客单价、营收同比(`LOOKUP`)、帕累托累计占比、缺货率、缺货 SKU 数、商机成单率、AI 辅助成单率、ROAS、CAC、AI 采纳率、AI 处理工单占比 …
- **10 个工作表**：销售月度趋势、渠道销售结构、客户层级贡献、商品帕累托、客户RFM散点、商机漏斗、库存健康、渠道投放效率、AI使用效能、工单与AI承接
- **3 个仪表板**：经营总览 / 销售与客户 / 库存与增长

```bash
python bi/tableau/build_twb.py && python bi/tableau/verify_twb.py   # 生成 + 结构自检
```

---

## 5. 数据模型

```
                    ┌────────────┐
                    │  dim_date  │  2024-01-01 ~ 2026-03-31
                    └─────┬──────┘
      ┌───────────┬───────┼────────┬─────────────┬──────────────┐
      │           │       │        │             │              │
┌─────▼─────┐ ┌───▼────┐ ┌▼────────┐ ┌▼─────────┐ ┌▼──────────┐
│dim_customer│ │dim_    │ │fact_   │ │fact_    │ │fact_      │
│dim_product │ │employee│ │sales_  │ │inventory│ │lead_      │
│dim_supplier│ └────────┘ │order*  │ │snapshot │ │opportunity│
                         └─────────┘ └─────────┘ └───────────┘
```

| 表 | 粒度 | 行数量级 |
|---|---|---|
| `dim_date` | 一天 | 822 |
| `dim_customer` | 一个客户 | 60 |
| `dim_employee` | 一个员工 | 18 |
| `dim_product` | 一个 SKU | 80 |
| `dim_supplier` | 一个供应商 | 12 |
| `fact_sales_order` | 一个订单 | ~5.7k |
| `fact_sales_order_item` | 一个订单行 | ~15.2k |
| `fact_inventory_snapshot` | 月 × 仓库 × 商品 | ~3.8k |
| `fact_lead_opportunity` | 一个线索/商机 | ~1.0k |
| `fact_customer_ticket` | 一个工单 | ~765 |
| `fact_marketing_spend` | 一次投放 | ~144 |
| `fact_ai_usage` | 一条 AI 使用记录 | ~1.2k |

---

## 6. API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | 登录，换访问令牌 + 刷新令牌 |
| POST | `/api/auth/refresh` | 刷新令牌轮换（旧令牌立即失效） |
| POST | `/api/auth/logout` | 吊销刷新令牌 |
| GET | `/api/auth/me` | 当前用户 |
| GET | `/api/dashboard/summary` | 经营总览 KPI（含同比/环比） |
| GET | `/api/dashboard/sales-trend` | 月度营收趋势 |
| GET | `/api/dashboard/top-customers` | Top 客户 |
| GET | `/api/dashboard/top-products` | Top 商品 |
| GET | `/api/dashboard/breakdown/{dimension}` | 按行业/区域/渠道/团队拆解 |
| GET | `/api/dashboard/funnel` | 线索 → 商机 → 成单漏斗 |
| GET | `/api/dashboard/inventory-health` | 库存健康度 |
| GET | `/api/analytics/ai-value` | AI 价值量化（商机/工单/助手三组对照） |
| GET | `/api/analytics/rfm` | 客户 RFM 分层 |
| GET | `/api/analytics/marketing` | 营销渠道效率（CAC/ROAS） |
| GET | `/api/ai/insights` | 自动经营洞察（每条附**证据 SQL**） |
| GET | `/api/products` `/api/customers` `/api/sales-orders` | 分页列表 |
| GET | `/api/sales-orders/{id}` | 订单详情（含明细） |
| POST | `/api/sales-orders` | 创建订单（**校验库存并写收发存流水**） |
| GET | `/api/inventory` | 最新库存快照 |
| GET | `/health` `/ready` | 健康检查 |

**演示账号**（`/api/auth/login`）：

| 账号 | 密码 | 角色 | 能做什么 |
|---|---|---|---|
| `admin` | `Admin@123456` | admin | 全部 |
| `analyst` | `Analyst@123456` | analyst | 读 + 分析 + 下单 |
| `sales` | `Sales@123456` | sales | 读 + 下单 |
| `viewer` | `Viewer@123456` | viewer | 只读（下单返回 403） |

---

## 7. 口径一致性是怎么保证的

这是本项目的**工程核心**，也是面试时最值得讲的部分：

| 层次 | 落地方式 |
|---|---|
| 文档 | `docs/数据字典与业务口径.md` 是**唯一口径来源**，其他文档一律引用它 |
| 数据库 | 营收口径在 `analytics_repo` / `order_service` 里集中实现，SQL 脚本口径一致 |
| Excel | `透视预分析` 公式页 + `透视结果_*` 静态页 + 透视表计算字段，三者同口径 |
| Power BI | 30 个 DAX 度量值，口径写死在度量值里（如 `[营收] = CALCULATE(SUM(...), order_status="已完成", is_return=0)`） |
| Tableau | 32 个计算字段，公式等价（如 `SUM(IF [order_status]="已完成" AND [is_return]=0 THEN [net_amount] END)`） |
| 校验 | `bi/verify_baselines.py`、`bi/tableau/verify_twb.py`、`bi/powerbi/verify_pbip.py`、`tests/test_api.py`、`scripts/_run_sql_analysis.py` |
| 数据质量 | 库存收发存对账差异 = 0；全期无负库存；种子随机种子固定为 42，任何机器结果一致 |

**验证命令**：

```bash
python scripts/_run_sql_analysis.py     # 20 个 SQL 脚本逐个执行 + 回填预期结果
python scripts/_gen_sql_verification.py # 生成 sql/_验证结果.md（真实执行结果汇总）
python bi/verify_baselines.py           # BI 基线数值核对
python bi/tableau/verify_twb.py         # Tableau 工作簿结构校验
python bi/powerbi/verify_pbip.py        # PBIP 项目结构校验
pytest tests/ -v                       # API 冒烟（含 RBAC / 库存不足 / 令牌轮换 / 库存对账）
```

> MySQL 侧验证需要先起一个 MySQL 8 实例，方式见 `scripts/_verify_mysql_instance.md`
> （本机已装 MySQL Server 8.0，可直接用；也支持不碰现有实例的临时实例方案）。

---

## 8. AI 产品销售思考 —— `docs/AI产品销售思考.md`

不是泛泛而谈"AI 会改变销售"，而是把想法落成**可算的模型**：

- **痛点地图**：把 ERP 里的真实数据映射到销售漏斗的每一环（线索质量差 / 报价慢 / 跟进断 / 报表难）
- **产品切入点**：每个痛点对应哪个 AI 能力（自然语言取数 / 预测性维护 / 自动摘要 / 客户分层）
- **ROI 测算**：用仓库里真实数据算「AI 节省工时 → 折算人力 → 对比投入」
- **销售 SOP**：从试用到成单的阶段动作、每阶段的判定标准与所需证据
- **异议处理**：价格质疑 / 数据安全质疑 / "我们已经有 BI 了" 三类反对意见的应对
- **合规与风险**：数据脱敏、模型可解释、客户数据不外泄

配套脚本：`scripts/AI产品销售思考_ROI测算.py`、`scripts/AI产品销售思考_校验取数脚本.py`、
`docs/AI产品销售思考_取数脚本.sql` —— **所有数字都从真实数据库取**，不编造。

---

## 9. 切换到 MySQL 8

默认 SQLite 零配置。要演示 MySQL（面试时加分，展示两种都熟）：

**本机已装 MySQL Server 8.0**（`C:\Program Files\MySQL\MySQL Server 8.0`，服务 `MySQL80`）。
拿到 root 密码后：

```bash
# 建库 + 导 schema
mysql -u root -p -e "CREATE DATABASE erp_analytics CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
mysql -u root -p erp_analytics < sql/mysql/schema.sql

# 用同一套 ORM 灌数（顺带验证双方言能力）
export DATABASE_URL="mysql+pymysql://root:密码@127.0.0.1:3306/erp_analytics"
python scripts/seed_db.py --reset        # 行数与 SQLite 完全一致，对账差异 = 0

# 跑 MySQL 版脚本并与 SQLite 逐值比对
python scripts/_run_sql_analysis.py --mysql --fill
python scripts/_compare_sql_dialects.py
```

或用 Docker：

```bash
docker compose up -d          # mysql:8.4，utf8mb4，自动执行 sql/mysql/schema.sql
export DATABASE_URL="mysql+pymysql://erp:erp123456@127.0.0.1:3306/erp_analytics"
python scripts/seed_db.py --reset
```

> **注意**：网页版 Docker Desktop 的容器跑在云端，本地 FastAPI 连不上它的 `3306`。
> 要连本地 MySQL，必须用**桌面版 Docker Desktop** 或本机安装的 MySQL。
> 不想动现有实例的话，`scripts/_verify_mysql_instance.md` 给了「起一个独立临时实例、用完即删」的方案。

---

## 10. 常见问题

| 现象 | 原因与处理 |
|---|---|
| Excel 打开只能看不能改 | Office 许可过期（只读模式）。激活 Office 后可运行 `pivot_macro.bas` 生成真透视表；未激活时用 `透视结果_*` + `透视预分析` 页 |
| Power BI 打开 `.pbip` 报错 | 你的 Power BI Desktop 版本较旧或为 Store 版。用兜底方案：`powerquery/erp_model.pq` + `dax/dax_measures.dax` + `model.md` 手工搭（见 `bi/powerbi/build_guide.md`） |
| Tableau 打开后字段为空 | 确认打开的是 `.twbx`（自带 Data/），而非 `.twb`（依赖外部 CSV 路径） |
| 端口被占用 | `uvicorn app.main:app --port 8001` |
| 依赖装不上 | `pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
