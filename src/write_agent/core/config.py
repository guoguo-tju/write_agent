"""
配置管理 - 类似 Java 的 @ConfigurationProperties
"""
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API 配置
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = True

    # OpenAI 兼容 API 配置
    # 保留 MINIMAX_* 作为兼容别名，避免历史环境变量立即失效。
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "MINIMAX_API_KEY"),
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("OPENAI_BASE_URL", "MINIMAX_BASE_URL"),
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_MODEL", "MINIMAX_MODEL"),
    )
    openai_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("OPENAI_TIMEOUT_SECONDS", "MINIMAX_TIMEOUT_SECONDS"),
    )

    # 硅基流动 Embedding API 配置
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn"
    siliconflow_embedding_model: str = "BAAI/bge-m3"

    # 火山引擎/即梦 API 配置
    volcengine_api_key: str = ""
    volcengine_base_url: str = "https://ark.cn-beijing.volces.com"
    volcengine_model: str = "doubao-seedream-4-5-251128"
    cover_storage_dir: str = "./data/covers"
    cover_media_url_prefix: str = "/media/covers"
    cover_prompt_llm_timeout_seconds: float = 12.0

    # GitHub 趋势
    github_token: str = Field(
        default="",
        validation_alias=AliasChoices("GITHUB_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN"),
    )
    github_trending_timezone: str = "Asia/Shanghai"
    github_trending_daily_hour: int = 9
    github_trending_daily_minute: int = 5

    # 小红书热点（第三方已授权数据服务）
    xhs_trends_provider: str = "algovate_mcp"  # algovate_mcp|http_api
    xhs_trends_api_base_url: str = ""
    xhs_trends_api_key: str = ""
    xhs_trends_timeout_seconds: float = 12.0
    xhs_trends_timezone: str = "Asia/Shanghai"
    xhs_trends_lookback_days: int = 7
    xhs_trends_min_interactions: int = 100
    xhs_trends_default_limit: int = 10
    xhs_trends_cache_file: str = "./data/xhs_trends_cache.json"
    xhs_trends_categories_file: str = "./src/write_agent/config/xhs_trends_categories.json"
    xhs_mcp_url: str = "http://127.0.0.1:3000/mcp"
    xhs_mcp_timeout_seconds: float = 20.0
    xhs_mcp_browser_path: str = ""
    xhs_trends_max_keywords_per_category: int = 5
    xhs_trends_comment_detail_limit: int = 3
    xhs_trends_comment_enrichment_ttl_seconds: int = 1800
    xhs_mcp_detail_interval_seconds: float = 0.8
    xhs_mcp_detail_retries: int = 1
    xhs_mcp_detail_retry_backoff_seconds: float = 1.0

    # 数据库配置
    database_url: str = "sqlite:///./data/acceptance_write_agent.db"

    # 日志配置
    log_level: str = "INFO"

    # 可观测性
    obs_enabled: bool = True
    obs_mode: str = "shadow"  # shadow|active
    obs_retention_days: int = 14
    obs_log_dir: str = "./data/observability"
    obs_token: str = ""
    obs_strict_dev: bool = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
