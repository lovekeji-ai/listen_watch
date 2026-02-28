import os
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个语音备忘录整理助手。用户会给你一段语音转写的原始文本（中文为主），请完成以下任务并以 JSON 格式返回结果：

1. **title**：根据内容提炼一个简短标题，10 字以内
2. **summary**：1~3 句话概括核心内容
3. **todos**：提取所有待办事项，返回字符串数组；若无待办事项则返回空数组 []
4. **cleaned_text**：去除语气词（嗯、啊、那个、就是等）、修正口语化表达，整理为通顺的书面文字

只返回 JSON，不要有任何多余的解释或 markdown 代码块。格式：
{"title": "...", "summary": "...", "todos": ["...", "..."], "cleaned_text": "..."}"""


@dataclass
class ProcessedMemo:
    title: str
    summary: str
    todos: List[str] = field(default_factory=list)
    cleaned_text: str = ""
    original_text: str = ""   # 原始转写文本，由调用方填入，不经过 AI
    memo_title: str = ""      # iOS 录音标题（如"录音 53"），由调用方填入


class KimiProcessor:
    BASE_URL = "https://api.moonshot.cn/v1"
    MODEL = "kimi-k2-0711-preview"

    def __init__(self):
        self._client = OpenAI(
            api_key=os.getenv("KIMI_API_KEY", ""),
            base_url=self.BASE_URL,
        )

    def process(self, text: str) -> ProcessedMemo:
        response = self._client.chat.completions.create(
            model=self.MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        return _parse_response(raw)


class DeepSeekProcessor:
    BASE_URL = "https://api.deepseek.com/v1"
    MODEL = "deepseek-chat"

    def __init__(self):
        self._client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=self.BASE_URL,
        )

    def process(self, text: str) -> ProcessedMemo:
        response = self._client.chat.completions.create(
            model=self.MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        return _parse_response(raw)


class ClaudeProcessor:
    MODEL = "claude-sonnet-4-6"

    def __init__(self):
        # 延迟导入，仅在使用 Claude 时才需要 anthropic 包
        import anthropic
        self._client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    def process(self, text: str) -> ProcessedMemo:
        message = self._client.messages.create(
            model=self.MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        raw = message.content[0].text.strip()
        return _parse_response(raw)


def _parse_response(raw: str) -> ProcessedMemo:
    """解析 AI 返回的 JSON，容忍 markdown 代码块包裹。"""
    # 去掉可能的 ```json ... ``` 包裹
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    data = json.loads(raw)
    return ProcessedMemo(
        title=data.get("title", ""),
        summary=data.get("summary", ""),
        todos=data.get("todos", []),
        cleaned_text=data.get("cleaned_text", ""),
    )


_PROVIDERS = {
    "kimi": KimiProcessor,
    "deepseek": DeepSeekProcessor,
    "claude": ClaudeProcessor,
}


def get_processor(provider: Optional[str] = None):
    """根据 AI_PROVIDER 环境变量返回对应的处理器实例。"""
    name = (provider or os.getenv("AI_PROVIDER", "kimi")).lower()
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"未知的 AI_PROVIDER: {name}，可选值：{list(_PROVIDERS)}")
    logger.debug("使用 AI 处理器: %s", name)
    return cls()


def process(text: str) -> ProcessedMemo:
    """
    主入口：读取 AI_PROVIDER 配置，调用对应服务处理转写文本。
    主服务失败时自动切换到 AI_FALLBACK_PROVIDER。
    """
    primary = os.getenv("AI_PROVIDER", "kimi")
    fallback = os.getenv("AI_FALLBACK_PROVIDER", "")

    try:
        processor = get_processor(primary)
        logger.info("AI 处理中（%s）...", primary)
        result = processor.process(text)
        logger.info("AI 处理完成：%s", result.title)
        return result
    except Exception as e:
        if not fallback or fallback == primary:
            raise
        logger.warning("主服务 %s 失败（%s），切换到备用服务 %s", primary, e, fallback)
        processor = get_processor(fallback)
        result = processor.process(text)
        logger.info("AI 处理完成（备用 %s）：%s", fallback, result.title)
        return result
