# 在本机 MySQL 8 上验证 SQL 脚本

> 目标：用**真实的 MySQL 8** 跑一遍 `sql/mysql/analysis/` 的 20 个脚本，
> 并与 SQLite 版本逐行逐列比对，验证「口径跨数据库一致」。

---

## 方案 A：用本机已安装的 MySQL（推荐，本机已装 MySQL Server 8.0）

本机检测结果：`C:\Program Files\MySQL\MySQL Server 8.0`，服务名 `MySQL80`，监听 3306。

### A1. 找到 root 密码

MySQL 8 的 root 密码可能存在 Windows 凭据管理器里。可选做法：

```powershell
# 查看 Workbench 保存的连接
Get-Content "$env:APPDATA\MySQL\Workbench\connections.xml"
# 查看凭据管理器中的 MySQL 条目
cmdkey /list | Select-String -Pattern "MySQL" -Context 0,3
```

知道密码后直接用：

```powershell
$env:MYSQL_PWD = "你的密码"
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -e "SELECT VERSION();"
```

### A2. 建库并导入 schema

```bash
BASE="/c/Program Files/MySQL/MySQL Server 8.0"
export MYSQL_PWD="你的密码"

"$BASE/bin/mysql.exe" -u root -e "DROP DATABASE IF EXISTS erp_analytics;
  CREATE DATABASE erp_analytics CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
"$BASE/bin/mysql.exe" -u root erp_analytics < sql/mysql/schema.sql
```

### A3. 用同一套 ORM 灌种子数据（**验证双方言能力**）

```bash
export MSYS_NO_PATHCONV=1
export DATABASE_URL="mysql+pymysql://root:你的密码@127.0.0.1:3306/erp_analytics"
python scripts/seed_db.py --reset
```

输出里应看到与 SQLite **完全相同**的行数与 `_库存对账.差异 = 0`：

```json
"_库存对账": { "期初建账": 13380, "采购入库": 85198, "销售出库": -80339,
               "退货入库": 1211, "报废": 50, "期末快照(末月)": 19500,
               "推算期末": 19500, "差异": 0, "对账通过": true }
```

### A4. 执行与比对

```bash
python scripts/_run_sql_analysis.py --mysql --fill     # MySQL 版执行 + 回填预期结果
python scripts/_compare_sql_dialects.py                # 逐值比对
```

---

## 方案 B：用 Docker（不碰本机 MySQL）

```bash
docker compose up -d
# 等 MySQL 起来
export MSYS_NO_PATHCONV=1
export DATABASE_URL="mysql+pymysql://erp:erp123456@127.0.0.1:3306/erp_analytics"
python scripts/seed_db.py --reset
python scripts/_run_sql_analysis.py --mysql --fill
python scripts/_compare_sql_dialects.py
```

> ⚠️ **网页版 Docker Desktop 不行**：它的容器跑在云端，本地 FastAPI / MySQL 客户端
> 连不上它的 `3306`。要连本地 MySQL 必须用**桌面版 Docker Desktop** 或本机安装的 MySQL。

---

## 方案 C：起一个隔离的临时 MySQL 实例（**不碰你现有的实例与数据**）

不想动已有 MySQL 时，用独立数据目录起一个临时实例：

```bash
BASE="/c/Program Files/MySQL/MySQL Server 8.0"
TMP="$TEMP/erp_mysql_verify"

# 1) 初始化独立数据目录（root 空密码，仅本机临时用）
mkdir -p "$TMP/data"
"$BASE/bin/mysqld.exe" --initialize-insecure \
    --basedir="$BASE" --datadir="$(cygpath -w "$TMP/data")" --console

# 2) 后台启动在 3307
"$BASE/bin/mysqld.exe" --basedir="$(cygpath -w "$BASE")" \
    --datadir="$(cygpath -w "$TMP/data")" --port=3307 --mysqlx=0 --console

# 3) 建库 + 导 schema + 灌数 + 跑比对
"$BASE/bin/mysql.exe" -u root --protocol=TCP -h 127.0.0.1 -P 3307 \
    -e "CREATE DATABASE erp_analytics CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
"$BASE/bin/mysql.exe" -u root --protocol=TCP -h 127.0.0.1 -P 3307 erp_analytics < sql/mysql/schema.sql

export MSYS_NO_PATHCONV=1
export DATABASE_URL="mysql+pymysql://root@127.0.0.1:3307/erp_analytics"
python scripts/seed_db.py --reset
python scripts/_run_sql_analysis.py --mysql --fill
python scripts/_compare_sql_dialects.py

# 4) 收工：关停并清理（不影响你 3306 上的实例）
"$BASE/bin/mysqladmin.exe" -u root --protocol=TCP -h 127.0.0.1 -P 3307 shutdown
rm -rf "$TMP"
```

> 这就是本项目实际采用的验证方式 —— **完全不触碰用户已有的 MySQL 实例与数据**，
> 用完即删。

---

## 比对脚本的环境变量

`scripts/_compare_sql_dialects.py` 与 `scripts/_run_sql_analysis.py --mysql` 读这些变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ERP_MYSQL_HOST` | `127.0.0.1` | |
| `ERP_MYSQL_PORT` | `3307` | 方案 B 用 3306 |
| `ERP_MYSQL_USER` | `root` | |
| `ERP_MYSQL_PASSWORD` | 空 | |
| `ERP_MYSQL_DB` | `erp_analytics` | |

也可以直接用命令行参数：

```bash
python scripts/_compare_sql_dialects.py --mysql-host 127.0.0.1 --mysql-port 3306 \
    --mysql-user erp --mysql-password erp123456 --mysql-db erp_analytics
```

---

## 判定标准

| 情况 | 判定 |
|---|---|
| 20 个脚本全部 PASS，跨方言逐值一致 | ✅ 完全一致 |
| 少数脚本报「末位精度差异」且相对误差 ≤ 5e-3 | ⚠️ 引擎数值语义差异，可解释（见口径文档 §6.2） |
| 出现「口径不一致」 | ❌ 真问题，必须修 |

口径文档：`docs/数据字典与业务口径.md` 第 6 节。
验证汇总：`sql/_验证结果.md`。
