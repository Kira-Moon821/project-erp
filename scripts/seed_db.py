"""建库 + 灌种子数据。

用法：
    python scripts/seed_db.py            # 建表并灌数（已有数据则跳过）
    python scripts/seed_db.py --reset    # 清空业务表后重建
"""
from __future__ import annotations

import argparse
import decimal
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings          # noqa: E402
from app.db.seed import run_seed                  # noqa: E402
from app.db.session import create_all, session_scope  # noqa: E402


def _json_default(o):
    """MySQL 的 DECIMAL 会被 SQLAlchemy 映射成 Decimal，这里转 float 便于阅读。"""
    if isinstance(o, decimal.Decimal):
        return float(o)
    return str(o)


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 ERP 分析实验室数据库")
    parser.add_argument("--reset", action="store_true", help="先清空业务表再重建")
    args = parser.parse_args()

    settings = get_settings()
    if settings.is_sqlite:
        db_path = ROOT / settings.database_url.replace("sqlite:///", "").lstrip("/")
        db_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    create_all()
    with session_scope() as session:
        result = run_seed(session, settings, reset=args.reset)
    result["elapsed_seconds"] = round(time.time() - started, 2)
    result["database"] = settings.database_url
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
