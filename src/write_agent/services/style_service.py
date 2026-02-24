"""
风格提取服务 - 从参考文章中提取写作风格
"""
import json
from typing import Generator, Optional
from sqlmodel import Session, create_engine, select
from datetime import datetime

from write_agent.core import get_settings, get_logger
from write_agent.models.writing_style import WritingStyle
from write_agent.services.llm_service import get_llm_service

logger = get_logger(__name__)
settings = get_settings()

# 创建数据库引擎
engine = create_engine(settings.database_url, echo=False)


# 风格提取的 Prompt - 基于 12 维度深度解构
# 参考自风格建模 skill: https://...
STYLE_EXTRACTION_PROMPT = """你是一个专业的写作风格建模专家。请对以下参考文章进行深度解构，提取"写作配方"。

## 核心理念
风格建模不是写评论，而是提取"写作配方"——让任何人拿着这份配方都能写出相似的文章。

## 十二维度深度解构

请严格按照以下 12 个维度进行分析：

### 维度一：核心人格与立场 (Persona & Stance)
- 作者人设：他在读者面前是什么角色？（导师？朋友？愤青？旁观者？）
- 对读者的态度：俯视教导？平视聊天？仰视请教？
- 价值观倾向：反鸡汤？反主流？反精英？拥抱真实？
- 情绪基调：愤怒？讽刺？温和？玩世不恭？

### 维度二：思维模式与论证逻辑 (Thinking Pattern)
- 典型论证结构：是"现象→质疑→反转→结论"？还是"观点→例证→升华"？
- 反常识/反直觉手法：是否经常推翻读者预期？
- 类比与联想：是否经常用跨领域类比？用什么领域？

### 维度三：开头模式 (Opening Pattern)
- 开头句式：是直接抛观点？提问？场景描写？引用？
- 开头长度：第一段通常几句话？
- 开头节奏：快速切入还是缓慢铺垫？
- 禁忌检查：是否避开"在当今社会"等AI套路？

### 维度四：段落过渡模式 (Transition Pattern)
- 段落间如何衔接：无过渡直接跳？用反问引导？用短句情绪转折？
- 是否使用"首先/其次/最后"：如果不用，用什么替代？
- 话题切换信号词：典型切换词（如"说到这个"、"但问题是"）

### 维度五：句式与节奏 (Sentence & Rhythm)
- 句子长度分布：长句和短句的比例
- 标点习惯：是否大量使用逗号形成长句？是否用省略号？感叹号频率？
- 段落长度分布：最短的段落几句？最长的段落几句？

### 维度六：词汇指纹 (Vocabulary Fingerprint)
- 高频词汇：提取出现3次以上的特色词汇
- 口头禅/招牌表达：如"说白了"、"本质上"、"其实就是"
- 禁用词汇：哪些词从未出现？（如"赋能"、"抓手"）
- 粗俗程度：是否使用粗话？程度如何？

### 维度七：修辞手法 (Rhetorical Devices)
- 反问频率：每篇文章大约几个反问？
- 排比使用：是否使用排比？如何使用？
- 比喻偏好：喜欢用什么类型的比喻？
- 夸张程度：是否经常使用夸张手法？

### 维度八：结尾模式 (Ending Pattern)
- 结尾句式：是戛然而止？回扣开头？留悬念？发出号召？
- 结尾长度：最后一段通常几句话？
- 是否有"升华"：是否有假大空结尾？

### 维度九：格式与排版 (Format & Layout)
- 小标题使用：完全不用？偶尔用？每段都用？
- 加粗使用：从不加粗？只加粗关键词？
- 列表使用：是否使用项目符号列表？

### 维度十：独特习惯与招牌动作 (Signature Moves)
提取最具辨识度的3-5个"招牌动作"：
- 例如：总是在文章中途突然自问自答
- 例如：喜欢用"........."省略号制造停顿

### 维度十一：反AI特征 (Anti-AI Features)
- 哪些特征是AI很难模仿的？
- 哪些"不规则性"是刻意为之？
- 哪些表达方式会让读者立刻感觉"这不是AI写的"？

### 维度十二：典型段落模板 (Paragraph Templates)
从样本中提取最具代表性的段落模板：
- 观点段模板
- 举例段模板
- 转折段模板
- 收尾段模板

## 输出要求

请用 JSON 格式输出，结构如下（所有字段必填，如果没有则写"无"）：
{{
    "persona": "核心人格描述",
    "thinking_pattern": "思维模式描述",
    "opening_pattern": "开头模式描述",
    "transition_pattern": "过渡模式描述",
    "sentence_rhythm": "句式节奏描述",
    "vocabulary": "词汇指纹",
    "rhetorical_devices": "修辞手法描述",
    "ending_pattern": "结尾模式描述",
    "format_layout": "格式排版描述",
    "signature_moves": ["招牌动作1", "招牌动作2", "招牌动作3"],
    "anti_ai_features": "反AI特征描述",
    "paragraph_templates": {{
        "观点段": "模板示例",
        "举例段": "模板示例",
        "转折段": "模板示例",
        "收尾段": "模板示例"
    }},
    "overall_summary": "总体风格概括（100字以内）"
}}

参考文章：
{article_content}"""


class StyleExtractionService:
    """
    风格提取服务
    """

    def _combine_articles(self, articles: list[str]) -> str:
        """清洗并合并参考文章内容。"""
        cleaned = [article.strip() for article in articles if article and article.strip()]
        return "\n\n---\n\n".join(cleaned[:5])  # 最多5篇

    def _clean_style_json(self, raw_content: str) -> str:
        """清理模型返回并确保是可解析 JSON。"""
        style_json = raw_content.strip()
        if "```json" in style_json:
            style_json = style_json.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in style_json:
            style_json = style_json.split("```", 1)[1].split("```", 1)[0]

        style_json = style_json.strip()
        try:
            json.loads(style_json)
            return style_json
        except Exception:
            start = style_json.find("{")
            end = style_json.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = style_json[start:end + 1].strip()
                json.loads(candidate)
                return candidate
            raise ValueError("模型未返回有效的 JSON 风格描述")

    def _save_style(
        self,
        style_name: str,
        style_json: str,
        combined_content: str,
        tags: Optional[str] = None,
    ) -> WritingStyle:
        """保存风格到数据库。"""
        with Session(engine) as session:
            writing_style = WritingStyle(
                name=style_name,
                style_description=style_json,
                example_text=combined_content[:1000],  # 保存部分示例
                tags=tags,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            session.add(writing_style)
            session.commit()
            session.refresh(writing_style)
            return writing_style

    def extract_style(
        self,
        articles: list[str],
        style_name: str,
        tags: Optional[str] = None,
    ) -> WritingStyle:
        """
        从多篇文章中提取写作风格

        Args:
            articles: 参考文章列表
            style_name: 风格名称
            tags: 标签

        Returns:
            WritingStyle 对象
        """
        logger.info(f"开始提取写作风格: {style_name}")

        # 合并文章内容
        combined_content = self._combine_articles(articles)
        if not combined_content:
            raise ValueError("请提供至少一篇有效参考文章")

        # 调用 LLM 提取风格
        llm = get_llm_service()
        raw_content = llm.chat(
            messages=[{"role": "user", "content": STYLE_EXTRACTION_PROMPT.format(
                article_content=combined_content
            )}],
            system_prompt="你是一个专业的写作风格建模专家。请严格按照JSON格式输出12个维度的分析结果，不要添加其他内容。确保所有JSON字段都是有效的。",
        )

        # 清理 JSON（可能包含 markdown 标记）
        style_json = self._clean_style_json(raw_content)

        logger.info(f"风格提取完成: {style_name}")
        return self._save_style(style_name, style_json, combined_content, tags)

    def extract_style_stream(
        self,
        articles: list[str],
        style_name: str,
        tags: Optional[str] = None,
    ) -> Generator[dict, None, None]:
        """
        流式提取写作风格。

        Yields:
            SSE 事件字典
        """
        logger.info(f"开始流式提取写作风格: {style_name}")

        combined_content = self._combine_articles(articles)
        if not combined_content:
            raise ValueError("请提供至少一篇有效参考文章")

        llm = get_llm_service()
        raw_content = ""

        yield {
            "type": "start",
            "style_name": style_name,
            "articles_count": len([a for a in articles if a and a.strip()]),
        }
        yield {
            "type": "progress",
            "step": "analyzing",
            "message": "正在分析参考文章并提取12维风格特征...",
        }

        try:
            for chunk in llm.stream(
                messages=[{"role": "user", "content": STYLE_EXTRACTION_PROMPT.format(
                    article_content=combined_content
                )}],
                system_prompt=(
                    "你是一个专业的写作风格建模专家。"
                    "请严格按照JSON格式输出12个维度的分析结果，不要添加其他内容。"
                    "确保所有JSON字段都是有效的。"
                ),
            ):
                raw_content += chunk
                yield {"type": "content", "delta": chunk}

            style_json = self._clean_style_json(raw_content)
            writing_style = self._save_style(
                style_name=style_name,
                style_json=style_json,
                combined_content=combined_content,
                tags=tags,
            )

            logger.info(f"风格提取完成: {style_name}")
            yield {
                "type": "done",
                "id": writing_style.id,
                "name": writing_style.name,
                "style_description": writing_style.style_description,
                "tags": writing_style.tags,
                "created_at": writing_style.created_at.isoformat(),
            }
        except Exception as e:
            logger.error(f"流式提取风格失败: {e}")
            yield {"type": "error", "message": str(e)}

    def get_all_styles(self) -> list[WritingStyle]:
        """获取所有写作风格"""
        with Session(engine) as session:
            statement = select(WritingStyle).order_by(WritingStyle.created_at.desc())
            return session.exec(statement).all()

    def get_style_by_id(self, style_id: int) -> Optional[WritingStyle]:
        """根据ID获取写作风格"""
        with Session(engine) as session:
            return session.get(WritingStyle, style_id)

    def delete_style(self, style_id: int) -> bool:
        """删除写作风格"""
        with Session(engine) as session:
            style = session.get(WritingStyle, style_id)
            if style:
                session.delete(style)
                session.commit()
                return True
            return False


# 全局单例
_style_service: Optional[StyleExtractionService] = None


def get_style_service() -> StyleExtractionService:
    """获取风格提取服务单例"""
    global _style_service
    if _style_service is None:
        _style_service = StyleExtractionService()
    return _style_service
