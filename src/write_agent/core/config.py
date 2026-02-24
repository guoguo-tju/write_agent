"""
配置管理 - 类似 Java 的 @ConfigurationProperties
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # API 配置
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = True

    # MiniMax API 配置
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.chat/v1"
    minimax_model: str = "MiniMax-M2.1"

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
