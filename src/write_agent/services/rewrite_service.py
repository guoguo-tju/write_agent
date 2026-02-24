"""
改写服务 - 文章改写核心逻辑
"""
import json
import re
from typing import Optional, Generator
from urllib.parse import urlparse
from sqlmodel import Session, create_engine, select
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from write_agent.core import get_settings, get_logger
from write_agent.models import RewriteRecord, WritingStyle
from write_agent.services.llm_service import get_llm_service
from write_agent.services.material_service import get_material_service

logger = get_logger(__name__)
settings = get_settings()

# 创建数据库引擎
engine = create_engine(settings.database_url, echo=False)


THINK_OPEN_TAGS = ("<think>", "<thinking>", "<langchain>")
THINK_CLOSE_TAGS = ("</think>", "</thinking>", "</langchain>")
THINK_TAG_GUARD = max(len(tag) for tag in THINK_OPEN_TAGS + THINK_CLOSE_TAGS) - 1
IMAGE_PLACEHOLDER_PATTERN = re.compile(r"\[配图建议\|名称:[^\]]+\]")


def _find_first_tag(text: str, tags: tuple[str, ...]) -> tuple[int, str]:
    """在文本中找到最靠前出现的标签。"""
    positions = [(text.find(tag), tag) for tag in tags if text.find(tag) != -1]
    if not positions:
        return -1, ""
    positions.sort(key=lambda item: item[0])
    return positions[0]


def _sanitize_placeholder_fragment(text: str, fallback: str) -> str:
    cleaned = re.sub(r"\s+", "", text or "")
    cleaned = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", cleaned)
    return cleaned[:12] or fallback


# 改写 Prompt - 基于写作执行 skill 优化
REWRITE_PROMPT = """你是一个专业的文章改写专家。请根据指定的写作风格，将原文改写成一篇"像人写而不是AI写"的文章。

## 写作风格（12维度）
{style_description}

## 目标字数
约 {target_words} 字
**字数误差必须控制在 ±20% 以内**（即 {min_words}-{max_words} 字之间）

## 原文
{source_article}

## RAG 检索素材（可参考）
{rag_content}

## 核心要求

### 1. 字数控制（硬性要求！）
- 目标：约 {target_words} 字
- 允许范围：{min_words}-{max_words} 字
- 禁止严重超标：不能超过目标的 120%

### 2. 反AI写作技巧（必须遵守！）

**禁止的开头模式：**
- ❌ "在当今社会..."、"随着...的发展..."、"众所周知..."
- ✅ 直接抛出具体场景、尖锐问题、或有态度的判断

**禁止的过渡词：**
- ❌ "首先...其次...再次...最后..."、"第一点...第二点..."
- ✅ 用反问句引出话题，或直接切换（人说话经常跳跃）

**禁止的结尾模式：**
- ❌ "让我们共同期待..."、"总而言之..."、"综上所述..."
- ✅ 戛然而止，或留反问/悬念，或回扣开头

**AI高频词（禁止使用）：**
- ❌ 连接词："此外""然而""但是""不过""与此同时"
- ❌ 强调词："至关重要""关键性的""核心的""至关重要的"
- ❌ 抽象词："格局""织锦""持久""彰显"
- ❌ 动词："强调""突出""彰显""培养""促进"
- ❌ 套路词："赋能""抓手""底层逻辑""认知升级""降维打击"

**段落技巧：**
- ❌ 禁止：每段长度高度一致（格式洁癖）
- ✅ 推荐：段落长短交替，像呼吸一样

### 3. 风格执行
请严格按照风格文件中的以下维度执行：
- 核心人格：按照定义的人设、态度来写
- 思维模式：遵循定义的论证结构
- 开头配方：使用定义的开头句式
- 过渡配方：使用定义的替代词
- 招牌动作：尽量使用 3 个以上定义的招牌动作
- 段落模板：参考定义的段落模板

### 4. 输出要求
1. 输出纯文章内容，不要有额外说明
2. 不要输出字数统计
3. 在文中合适位置插入 2-4 个配图占位，格式必须是：
   [配图建议|名称:一句话命名|说明:适合配图的画面描述]
4. 直接开始写正文

请开始改写："""


class RewriteService:
    """
    改写服务

    实现文章改写功能，支持流式输出
    """

    def __init__(self):
        self.llm_service = get_llm_service()
        self.material_service = get_material_service()

    def _count_actual_words(self, content: str) -> int:
        """统计正文字符数（去掉配图占位标记和空白）。"""
        without_placeholders = IMAGE_PLACEHOLDER_PATTERN.sub("", content or "")
        without_space = re.sub(r"\s+", "", without_placeholders)
        return len(without_space)

    def _ensure_image_placeholders(self, content: str) -> str:
        """
        确保改写结果带有配图占位。

        若模型未按格式输出，则基于段落自动补齐，便于后续封面/配图流程联动。
        """
        if not content.strip():
            return content

        if IMAGE_PLACEHOLDER_PATTERN.search(content):
            return content

        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
        if not paragraphs:
            return content

        total_length = sum(len(p) for p in paragraphs)
        expected_count = 1 if total_length < 700 else (2 if total_length < 1500 else 3)

        candidate_indexes = sorted(
            set(
                idx
                for idx in (
                    max(0, len(paragraphs) // 4),
                    max(0, len(paragraphs) // 2),
                    max(0, (len(paragraphs) * 3) // 4),
                )
                if idx < len(paragraphs)
            )
        )
        if not candidate_indexes:
            candidate_indexes = [0]

        insert_map: dict[int, str] = {}
        for seq, para_idx in enumerate(candidate_indexes[:expected_count], start=1):
            snippet = _sanitize_placeholder_fragment(paragraphs[para_idx], f"场景{seq}")
            insert_map[para_idx] = (
                f"[配图建议|名称:{snippet}配图|说明:围绕“{snippet}”设计与段落语义一致的画面]"
            )

        lines: list[str] = []
        for idx, paragraph in enumerate(paragraphs):
            lines.append(paragraph)
            if idx in insert_map:
                lines.append(insert_map[idx])

        return "\n\n".join(lines)

    def _is_url_input(self, text: str) -> bool:
        """判断输入是否是 URL。"""
        try:
            parsed = urlparse(text.strip())
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

    def _fetch_url_content(self, url: str) -> Optional[str]:
        """抓取 URL 文本内容，优先支持微信公众号正文。"""
        try:
            parsed = urlparse(url)
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://mp.weixin.qq.com/"
                if "mp.weixin.qq.com" in parsed.netloc
                else f"{parsed.scheme}://{parsed.netloc}/",
            }
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # 微信公众号页面优先提取 #js_content，普通站点走通用抽取
            if "mp.weixin.qq.com" in parsed.netloc:
                title_node = soup.select_one("#activity-name")
                content_node = soup.select_one("#js_content")
                if content_node:
                    for node in content_node(["script", "style"]):
                        node.decompose()
                    title = title_node.get_text(" ", strip=True) if title_node else ""
                    content_text = content_node.get_text("\n", strip=True)
                    merged = f"{title}\n\n{content_text}".strip()
                    if merged:
                        return merged[:50000]

            for node in soup(["script", "style", "nav", "footer", "header"]):
                node.decompose()
            text = soup.get_text(separator="\n")
            lines = [line.strip() for line in text.split("\n")]
            merged = "\n".join(line for line in lines if line)
            return merged[:50000] if merged else None
        except Exception as e:
            logger.error(f"URL 抓取失败: {url}, error={e}")
            return None

    def create_rewrite(
        self,
        source_article: str,
        style_id: int,
        target_words: int = 1000,
        enable_rag: bool = False,
        rag_top_k: int = 3,
    ) -> RewriteRecord:
        """
        创建改写记录

        Args:
            source_article: 原文
            style_id: 写作风格ID
            target_words: 目标字数
            enable_rag: 是否启用 RAG
            rag_top_k: RAG 检索条数

        Returns:
            RewriteRecord 对象
        """
        source_article = (source_article or "").strip()

        # 支持直接输入 URL（尤其是公众号链接）
        if self._is_url_input(source_article):
            logger.info(f"检测到 URL 输入，尝试抓取正文: {source_article}")
            fetched_content = self._fetch_url_content(source_article)
            if not fetched_content:
                raise ValueError("无法从 URL 抓取内容，请粘贴原文后重试")
            source_article = fetched_content

        logger.info(f"创建改写任务: style_id={style_id}, target={target_words}字")

        # 获取写作风格
        with Session(engine) as session:
            style = session.get(WritingStyle, style_id)
            if not style:
                raise ValueError(f"风格不存在: {style_id}")

            # 创建改写记录
            record = RewriteRecord(
                source_article=source_article,
                style_id=style_id,
                target_words=target_words,
                enable_rag=enable_rag,
                rag_top_k=rag_top_k,
                status="running",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            session.add(record)
            session.commit()
            session.refresh(record)

            return record

    def rewrite(
        self,
        rewrite_id: int,
    ) -> Generator[str, None, None]:
        """
        执行改写（流式输出）

        Args:
            rewrite_id: 改写记录ID

        Yields:
            流式输出的内容块
        """
        with Session(engine) as session:
            record = session.get(RewriteRecord, rewrite_id)
            if not record:
                yield json.dumps({"type": "error", "message": "改写记录不存在"})
                return

            style = session.get(WritingStyle, record.style_id)
            if not style:
                yield json.dumps({"type": "error", "message": "风格不存在"})
                return

        try:
            # 1. RAG 检索（如果启用）
            rag_content = ""
            rag_retrieved = []
            if record.enable_rag:
                yield json.dumps({"type": "progress", "step": "rag", "message": "检索相关素材..."})
                rag_results = self.material_service.search_by_keywords(
                    query=record.source_article[:500],
                    top_k=record.rag_top_k,
                )
                if rag_results:
                    rag_content = "\n\n".join([
                        f"素材{i+1}：{r['content']}"
                        for i, r in enumerate(rag_results)
                    ])
                    rag_retrieved = rag_results

            # 2. 构建 Prompt
            yield json.dumps({"type": "progress", "step": "rewrite", "message": "正在改写..."})

            # 计算字数范围 (±20%)
            min_words = int(record.target_words * 0.8)
            max_words = int(record.target_words * 1.2)

            prompt = REWRITE_PROMPT.format(
                style_description=style.style_description,
                target_words=record.target_words,
                min_words=min_words,
                max_words=max_words,
                source_article=record.source_article,
                rag_content=rag_content or "（无相关素材）",
            )

            # 3. 流式调用 LLM
            stream_buffer = ""
            in_think_block = False
            final_content = ""
            for chunk in self.llm_service.stream(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="""你是一个专业的文章改写专家。
1. 改写时保持原文核心观点，但使用指定的写作风格
2. 直接输出文章内容，不要有任何思考过程
3. 不要输出任何 XML 标签（如<think>）
4. 输出纯文章内容，不要有额外说明""",
            ):
                stream_buffer += chunk

                while stream_buffer:
                    if in_think_block:
                        close_idx, close_tag = _find_first_tag(stream_buffer, THINK_CLOSE_TAGS)
                        if close_idx == -1:
                            if len(stream_buffer) > THINK_TAG_GUARD:
                                stream_buffer = stream_buffer[-THINK_TAG_GUARD:]
                            break
                        stream_buffer = stream_buffer[close_idx + len(close_tag):]
                        in_think_block = False
                        continue

                    open_idx, open_tag = _find_first_tag(stream_buffer, THINK_OPEN_TAGS)
                    stray_close_idx, stray_close_tag = _find_first_tag(stream_buffer, THINK_CLOSE_TAGS)

                    # 兼容模型输出残缺标签：如果先看到关闭标签，丢弃其前内容和关闭标签本身。
                    if stray_close_idx != -1 and (open_idx == -1 or stray_close_idx < open_idx):
                        stream_buffer = stream_buffer[stray_close_idx + len(stray_close_tag):]
                        continue

                    if open_idx == -1:
                        emit_len = max(0, len(stream_buffer) - THINK_TAG_GUARD)
                        if emit_len == 0:
                            break

                        visible_text = stream_buffer[:emit_len]
                        stream_buffer = stream_buffer[emit_len:]

                        visible_text = re.sub(r"\n{3,}", "\n\n", visible_text)
                        if visible_text:
                            final_content += visible_text
                            yield json.dumps({"type": "content", "delta": visible_text})
                        continue

                    visible_text = stream_buffer[:open_idx]
                    stream_buffer = stream_buffer[open_idx + len(open_tag):]
                    in_think_block = True

                    visible_text = re.sub(r"\n{3,}", "\n\n", visible_text)
                    if visible_text:
                        final_content += visible_text
                        yield json.dumps({"type": "content", "delta": visible_text})

            # flush 剩余可见文本
            if not in_think_block and stream_buffer:
                stream_buffer = re.sub(r"</?(?:think|thinking|langchain)>", "", stream_buffer)
                stream_buffer = re.sub(r"\n{3,}", "\n\n", stream_buffer)
                if stream_buffer:
                    final_content += stream_buffer
                    yield json.dumps({"type": "content", "delta": stream_buffer})

            final_content = self._ensure_image_placeholders(final_content)
            actual_words = self._count_actual_words(final_content)

            # 4. 保存结果
            with Session(engine) as session:
                record = session.get(RewriteRecord, rewrite_id)
                record.final_content = final_content
                record.actual_words = actual_words
                record.rag_retrieved = json.dumps(rag_retrieved, ensure_ascii=False)
                record.status = "completed"
                record.updated_at = datetime.now()
                session.commit()

            yield json.dumps({
                "type": "done",
                "final_content": final_content,
                "actual_words": actual_words,
            })

        except Exception as e:
            logger.error(f"改写失败: {e}")
            # 更新状态为失败
            with Session(engine) as session:
                record = session.get(RewriteRecord, rewrite_id)
                if record:
                    record.status = "failed"
                    record.error_message = str(e)
                    record.updated_at = datetime.now()
                    session.commit()

            yield json.dumps({"type": "error", "message": str(e)})

    def get_rewrite(self, rewrite_id: int) -> Optional[RewriteRecord]:
        """获取改写记录"""
        with Session(engine) as session:
            return session.get(RewriteRecord, rewrite_id)

    def get_rewrites(
        self,
        style_id: Optional[int] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[RewriteRecord], int]:
        """获取改写历史列表"""
        with Session(engine) as session:
            statement = select(RewriteRecord).order_by(RewriteRecord.created_at.desc())

            if style_id:
                statement = statement.where(RewriteRecord.style_id == style_id)

            # 统计总数
            count_statement = select(RewriteRecord)
            if style_id:
                count_statement = count_statement.where(RewriteRecord.style_id == style_id)
            total = len(session.exec(count_statement).all())

            # 分页
            statement = statement.offset((page - 1) * limit).limit(limit)
            records = session.exec(statement).all()

            return records, total


# 全局单例
_rewrite_service: Optional[RewriteService] = None


def get_rewrite_service() -> RewriteService:
    """获取改写服务单例"""
    global _rewrite_service
    if _rewrite_service is None:
        _rewrite_service = RewriteService()
    return _rewrite_service
