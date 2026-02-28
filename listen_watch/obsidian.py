import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JOURNAL_DIR = os.getenv("OBSIDIAN_JOURNAL_DIR", "")
DATE_FORMAT = os.getenv("OBSIDIAN_DATE_FORMAT", "%Y-%m-%d")
SECTION_HEADING = "## 语音记录"


def _journal_path(date: Optional[datetime] = None) -> Path:
    """返回当天日记文件的路径。"""
    d = date or datetime.now()
    filename = d.strftime(DATE_FORMAT) + ".md"
    return Path(JOURNAL_DIR) / filename


def _format_entry(memo, recorded_at: Optional[datetime] = None) -> str:
    """将 ProcessedMemo 格式化为 Markdown 条目。"""
    from listen_watch.processor import ProcessedMemo
    t = recorded_at or datetime.now()
    time_str = t.strftime("%H:%M")

    heading = f"### {time_str}"
    if memo.memo_title:
        heading += f" · {memo.memo_title}"
    heading += f" · {memo.title}"
    lines = [heading, ""]

    lines += [f"> {memo.summary}", ""]

    if memo.todos:
        lines += ["**待办事项**"]
        for todo in memo.todos:
            lines.append(f"- [ ] {todo}")
        lines.append("")

    lines += ["**原始转写**", memo.original_text, ""]

    return "\n".join(lines)


def append_memo(memo, recorded_at: Optional[datetime] = None) -> None:
    """
    将处理后的语音备忘录追加写入当天 Obsidian 日记。
    - 文件不存在：抛出 FileNotFoundError
    - 无 '## 语音记录' 章节：在文件末尾追加章节和条目
    - 章节已存在：在章节内末尾追加条目
    """
    path = _journal_path(recorded_at)
    if not path.exists():
        raise FileNotFoundError(f"当天日记文件不存在，请先在 Obsidian 中创建: {path}")

    entry = _format_entry(memo, recorded_at)
    content = path.read_text(encoding="utf-8")

    if SECTION_HEADING not in content:
        # 章节不存在，追加到文件末尾
        separator = "\n" if content.endswith("\n") else "\n\n"
        new_content = content + separator + SECTION_HEADING + "\n\n" + entry
        logger.info("未找到 '%s' 章节，已在文件末尾创建", SECTION_HEADING)
    else:
        # 章节存在，找到插入位置：--- 分隔线之前（或下一个 ## 标题之前）
        lines = content.splitlines(keepends=True)
        section_idx = None
        next_section_idx = len(lines)

        for i, line in enumerate(lines):
            if line.strip() == SECTION_HEADING:
                section_idx = i
            elif section_idx is not None and line.startswith("## "):
                next_section_idx = i
                break

        if section_idx is None:
            # 兜底：直接追加
            new_content = content.rstrip("\n") + "\n\n" + entry
        else:
            # 从下一个章节往前找 ---，在它之前插入
            insert_idx = next_section_idx
            for i in range(next_section_idx - 1, section_idx, -1):
                if lines[i].strip() == "---":
                    insert_idx = i
                    break

            before = "".join(lines[:insert_idx]).rstrip("\n")
            after = "".join(lines[insert_idx:])
            new_content = before + "\n\n" + entry + "\n" + after

    path.write_text(new_content, encoding="utf-8")
    logger.info("已写入日记: %s", path.name)
