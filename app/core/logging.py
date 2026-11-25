"""结构化 JSON 日志 + request_id 贯穿。

- 所有日志统一 JSON 行，便于采集与检索；
- request_id 通过 contextvar 贯穿请求全链路；
- 绝不记录密码、令牌、隐私字段。
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any, Dict

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_SENSITIVE = {"password", "password_hash", "token", "access_token", "refresh_token", "secret", "authorization"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {"args", "asctime", "exc_info", "exc_text", "stack_info", "levelname", "levelno",
                                             "name", "msg", "pathname", "filename", "module", "lineno", "funcName",
                                             "created", "msecs", "relativeCreated", "thread", "threadName",
                                             "processName", "process", "taskName"}:
                continue
            if key in _SENSITIVE:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = str(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    logging.getLogger("uvicorn.access").disabled = True


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]
