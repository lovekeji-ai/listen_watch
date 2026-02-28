import logging
import logging.handlers
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from mutagen.mp4 import MP4, MP4StreamInfoError
from listen_watch.watcher import VoiceMemoWatcher
from listen_watch.db import (
    init_db, is_processed, mark_success, mark_failed, get_unprocessed,
    get_transcription, get_ai_result, save_transcription, save_ai_result,
)

load_dotenv()

# ── 日志配置 ──────────────────────────────────────────────────────
LOG_DIR = Path.home() / ".listen_watch"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 控制台
_console = logging.StreamHandler()
_console.setFormatter(_formatter)

# 运行日志（按天滚动，保留 7 天）
_run_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_DIR / "listen_watch.log", when="midnight", backupCount=15, encoding="utf-8"
)
_run_handler.setFormatter(_formatter)

# 错误日志（按天滚动，保留 15 天）
_err_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_DIR / "error.log", when="midnight", backupCount=15, encoding="utf-8"
)
_err_handler.setLevel(logging.ERROR)
_err_handler.setFormatter(_formatter)

logging.basicConfig(level=logging.INFO, handlers=[_console, _run_handler, _err_handler])
logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────────────────
VOICE_MEMOS_DIR = os.getenv(
    "VOICE_MEMOS_DIR",
    str(Path.home() / "Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"),
)
MAX_TRANSCRIBE_MINUTES = float(os.getenv("MAX_TRANSCRIBE_MINUTES", "10"))

RETRY_DELAYS = [5, 15, 45]  # 指数退避间隔（秒）


# ── 工具函数 ──────────────────────────────────────────────────────
def parse_recorded_at(path: Path) -> Optional[datetime]:
    """从文件名解析录制时间，格式 YYYYMMDD HHMMSS-...，失败返回 None。"""
    m = re.match(r"(\d{8})\s(\d{6})", path.stem)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def get_audio_duration_seconds(path: Path) -> Optional[float]:
    """返回音频时长（秒），读取失败返回 None。"""
    try:
        audio = MP4(path)
        return audio.info.length
    except (MP4StreamInfoError, Exception) as e:
        logger.warning("无法读取音频时长 %s: %s", path.name, e)
        return None


def get_memo_title(path: Path) -> Optional[str]:
    """从 m4a 元数据读取 iOS 语音备忘录标题（©nam），读取失败返回 None。"""
    try:
        audio = MP4(path)
        titles = audio.tags.get("©nam")
        return titles[0] if titles else None
    except Exception as e:
        logger.warning("无法读取录音标题 %s: %s", path.name, e)
        return None


# ── 核心处理 ──────────────────────────────────────────────────────
def _process_once(path: Path) -> None:
    """
    执行完整处理流程（转写 → AI → 写入 Obsidian），各阶段结果独立缓存。
    重试时已完成的阶段直接读缓存，不重复调用 API。
    """
    from listen_watch.transcriber import transcribe
    from listen_watch.processor import process
    from listen_watch.obsidian import append_memo

    recorded_at = parse_recorded_at(path)

    # 阶段 1：转写（有缓存则跳过 OSS 上传和豆包调用）
    text = get_transcription(path)
    if text:
        logger.info("使用缓存转写结果: %s", path.name)
    else:
        text = transcribe(path)
        save_transcription(path, text)
        logger.info("转写结果: %s", text)

    # 阶段 2：AI 处理（有缓存则跳过 Kimi 调用）
    memo = get_ai_result(path)
    if memo:
        logger.info("使用缓存 AI 结果: %s", path.name)
    else:
        memo = process(text)
        memo.original_text = text
        memo.memo_title = get_memo_title(path)
        save_ai_result(path, memo)
        if memo.memo_title:
            logger.info("录音标题: %s", memo.memo_title)

    # 阶段 3：写入 Obsidian（每次重试都会重新执行）
    append_memo(memo, recorded_at=recorded_at)


def on_new_memo(path: Path) -> None:
    """新录音文件就绪后的处理入口，含重复检测和指数退避重试。"""
    if is_processed(path):
        logger.info("已处理过，跳过: %s", path.name)
        return

    size_kb = path.stat().st_size / 1024
    recorded_at = parse_recorded_at(path)

    if recorded_at and recorded_at.date() != datetime.now().date():
        logger.info(
            "录音日期 %s 与今天 %s 不一致，将写入对应日期的日记",
            recorded_at.strftime("%Y-%m-%d"),
            datetime.now().date(),
        )
    elif not recorded_at:
        logger.warning("无法从文件名解析录制时间，将使用当前时间: %s", path.name)

    duration = get_audio_duration_seconds(path)
    if duration is not None:
        minutes, seconds = divmod(int(duration), 60)
        logger.info(">>> 新备忘录就绪: %s (%.1f KB, %d:%02d)", path.name, size_kb, minutes, seconds)
    else:
        logger.info(">>> 新备忘录就绪: %s (%.1f KB, 时长未知)", path.name, size_kb)

    if MAX_TRANSCRIBE_MINUTES > 0 and duration is not None and duration > MAX_TRANSCRIBE_MINUTES * 60:
        logger.info(
            "文件时长 %.1f 分钟，超过限制 %.0f 分钟，跳过转写，仅记录文件路径。",
            duration / 60,
            MAX_TRANSCRIBE_MINUTES,
        )
        return

    last_error = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            _process_once(path)
            mark_success(path)
            return
        except Exception as e:
            last_error = e
            logger.warning("处理失败（第 %d 次），%d 秒后重试: %s", attempt, delay, e)
            time.sleep(delay)

    # 3 次均失败
    mark_failed(path)
    logger.error(
        "处理失败，已达最大重试次数，跳过文件 %s: %s",
        path.name, last_error, exc_info=True,
    )


# ── 入口 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    logger.info("listen_watch 启动")

    # 补处理启动前遗漏的文件
    missed = get_unprocessed(Path(VOICE_MEMOS_DIR))
    if missed:
        logger.info("发现 %d 个未处理文件，开始补处理...", len(missed))
        for p in missed:
            on_new_memo(p)

    watcher = VoiceMemoWatcher(VOICE_MEMOS_DIR, on_new_memo)
    watcher.run_forever()
    logger.info("listen_watch 已退出")
