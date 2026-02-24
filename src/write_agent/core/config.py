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

    # 硅基流动 Embedding API 配置
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn"
    siliconflow_embedding_model: str = "BAAI/bge-m3"

    # 火山引擎/即梦 API 配置
    volcengine_api_key: str = ""
    volcengine_base_url: str = "https://ark.cn-beijing.volces.com"
    volcengine_model: str = "doubao-seedream-4-5-251128"

    # 数据库配置
    database_url: str = "sqlite:///./data/acceptance_write_agent.db"

    # 日志配置
    log_level: str = "INFO"


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
