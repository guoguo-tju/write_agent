"""
LLM 服务封装 - 统一调用大模型
"""
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from typing import Optional

from write_agent.core import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class LLMService:
    """
    LLM 服务封装

    统一管理大模型调用，支持流式输出
    """

    def __init__(self):
        """初始化 LLM 客户端"""
        self.llm = ChatOpenAI(
            model=settings.minimax_model,
            openai_api_key=settings.minimax_api_key,
            base_url=settings.minimax_base_url
        )
        logger.info(f"LLM 服务初始化完成，使用模型: {settings.minimax_model}")

    def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        """
        简单的聊天调用

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            system_prompt: 系统提示
            temperature: 温度参数

        Returns:
            LLM 回复内容
        """
        # 构建消息
        langchain_messages = []
        if system_prompt:
            langchain_messages.append(SystemMessage(content=system_prompt))

        for msg in messages:
            if msg["role"] == "user":
                langchain_messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                langchain_messages.append(
                    {"type": "ai", "content": msg["content"]}
                )

        # 调用 LLM
        response = self.llm.invoke(langchain_messages)
        return response.content

    def stream(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
    ):
        """
        流式调用

        Args:
            messages: 消息列表
            system_prompt: 系统提示

        Yields:
            逐块返回的内容
        """
        # 构建消息
        langchain_messages = []
        if system_prompt:
            langchain_messages.append(SystemMessage(content=system_prompt))

        for msg in messages:
            if msg["role"] == "user":
                langchain_messages.append(HumanMessage(content=msg["content"]))

        # 流式调用
        for chunk in self.llm.stream(langchain_messages):
            if chunk.content:
                yield chunk.content


# 全局单例
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """获取 LLM 服务单例"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
