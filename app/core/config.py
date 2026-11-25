"""集中配置：全部来自环境变量 / .env，启动时集中校验，缺失即快速失败。

真实密钥只允许出现在 .env 或环境变量中，仓库内只保留 .env.example 占位值。
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_SECRETS = {"dev-only-change-me", "change-me", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "ERP Analytics Lab"
    environment: str = "local"
    api_prefix: str = "/api"
    log_level: str = "INFO"

    # 数据库：默认 SQLite 零配置可跑；切 MySQL 见 .env.example
    database_url: str = "sqlite:///./data/erp.db"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # 认证
    jwt_secret: str = Field(default="dev-only-change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    password_hash_iterations: int = 200_000

    # CORS 显式来源，生产禁用通配符
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # 限流（每分钟每 IP 允许的请求数）
    rate_limit_per_minute: int = 240

    # 种子数据
    seed_random_seed: int = 42
    seed_start_date: str = "2024-01-01"
    seed_end_date: str = "2025-12-31"

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        if not v.startswith(("sqlite://", "mysql+pymysql://")):
            raise ValueError("database_url 仅支持 sqlite:// 或 mysql+pymysql:// 两种驱动")
        return v

    @field_validator("cors_origins")
    @classmethod
    def _validate_cors(cls, v: str) -> str:
        if "*" in v and "environment" not in v:
            raise ValueError("cors_origins 禁止使用通配符 *，请显式列出来源")
        return v

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite://")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    def assert_runtime_ready(self) -> None:
        """启动时集中校验：生产环境不允许使用默认密钥。"""
        if self.is_production and self.jwt_secret in PLACEHOLDER_SECRETS:
            raise RuntimeError("生产环境必须通过环境变量 JWT_SECRET 配置强密钥，禁止使用默认值")
        if self.is_production and "*" in self.cors_origins:
            raise RuntimeError("生产环境 CORS 必须显式列出来源，禁止通配符")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_runtime_ready()
    return settings
