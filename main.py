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
    init_db, is_processed, mark_success, mark_skipped, mark_failed, get_unprocessed,
    get_transcription, save_transcription,
    save_file_info,
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
MIN_TRANSCRIBE_SECONDS = float(os.getenv("MIN_TRANSCRIBE_SECONDS", "3"))

RETRY_DELAYS = [5, 15, 45]  # 指数退避间隔（秒）


class EmptyTranscriptionError(Exception):
    """音频转写结果为空，应主动跳过而非重试。"""


# ── 工具函数 ──────────────────────────────────────────────────────
def ensure_directory_readable(path: Path, label: str) -> None:
    """校验目录存在且可读，失败时抛出带指引的异常。"""
    expanded = path.expanduser()
    if not expanded.exists():
        raise FileNotFoundError(f"{label}不存在: {expanded}")
    try:
        next(expanded.iterdir(), None)
    except PermissionError as e:
        raise PermissionError(
            f"{label}无读取权限: {expanded}。"
            "请在 macOS 系统设置 -> 隐私与安全性 中为运行该程序的 Python/终端/启动代理授予 Full Disk Access，"
            "并确认该目录已允许访问。"
        ) from e


def ensure_file_read_write(path: Path, label: str) -> None:
    """校验目标文件可读写，失败时抛出带指引的异常。"""
    expanded = path.expanduser()
    if not expanded.exists():
        raise FileNotFoundError(f"{label}不存在: {expanded}")
    try:
        with expanded.open("r+", encoding="utf-8"):
            pass
    except PermissionError as e:
        raise PermissionError(
            f"{label}无读写权限: {expanded}。"
            "请在 macOS 系统设置 -> 隐私与安全性 中为运行该程序的 Python/终端/启动代理授予 Documents/Full Disk Access 权限，"
            "或将 Obsidian 仓库移动到无额外权限限制的位置。"
        ) from e


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
def _transcribe_with_fallback(path: Path) -> str:
    """主路：豆包；豆包抛异常或返回空 → 用本地 whisper 兜底（若已配置）。"""
    from listen_watch.transcriber import transcribe as doubao_transcribe
    from listen_watch import local_whisper

    primary_error: Optional[Exception] = None
    text = ""
    try:
        text = doubao_transcribe(path)
    except Exception as e:
        primary_error = e
        logger.warning("豆包转写异常: %s", e)

    if text and text.strip():
        return text

    if not local_whisper.is_enabled():
        if primary_error is not None:
            raise primary_error
        return text  # 主路成功但内容为空，且未配置兜底 → 维持空

    logger.info("豆包结果不可用，启用本地 whisper 兜底: %s", path.name)
    try:
        return local_whisper.transcribe(path)
    except Exception as e:
        logger.error("本地 whisper 兜底也失败: %s", e)
        if primary_error is not None:
            raise primary_error
        raise


def _process_once(path: Path) -> None:
    """
    执行处理流程（转写 → 写入 Obsidian）。
    不再调用 AI 提取标题/摘要/待办，原文转写直接落盘。
    """
    from listen_watch.processor import ProcessedMemo
    from listen_watch.obsidian import append_memo

    recorded_at = parse_recorded_at(path)

    # 阶段 1：转写（有缓存则跳过 OSS 上传和豆包调用）
    text = get_transcription(path)
    if text:
        logger.info("使用缓存转写结果: %s", path.name)
    else:
        text = _transcribe_with_fallback(path)
        save_transcription(path, text)
        logger.info("转写结果: %s", text)

    if not text or not text.strip():
        raise EmptyTranscriptionError(f"转写结果为空: {path.name}")

    memo_title = get_memo_title(path) or ""
    if memo_title:
        logger.info("录音标题: %s", memo_title)
    memo = ProcessedMemo(
        title="",
        summary="",
        todos=[],
        cleaned_text="",
        original_text=text,
        memo_title=memo_title,
    )

    append_memo(memo, recorded_at=recorded_at)


def _get_today_unprocessed() -> list:
    """返回今天录制的、尚未成功处理的音频文件列表。"""
    today = datetime.now().date()
    result = []
    for p in get_unprocessed(Path(VOICE_MEMOS_DIR)):
        recorded_at = parse_recorded_at(p)
        if recorded_at:
            file_date = recorded_at.date()
        else:
            try:
                file_date = datetime.fromtimestamp(p.stat().st_mtime).date()
            except OSError:
                continue
        if file_date == today:
            result.append(p)
    return result


def _check_today_files() -> None:
    """检查并处理今天录制的所有未处理语音文件（写入后触发的补漏扫描）。"""
    missed = _get_today_unprocessed()
    if missed:
        logger.info("补漏扫描：发现 %d 个今日未处理文件", len(missed))
        for p in missed:
            on_new_memo(p, _check_missed=False)


def on_new_memo(path: Path, _check_missed: bool = True) -> None:
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

    save_file_info(path, get_memo_title(path), duration)

    if MAX_TRANSCRIBE_MINUTES > 0 and duration is not None and duration > MAX_TRANSCRIBE_MINUTES * 60:
        logger.info(
            "文件时长 %.1f 分钟，超过限制 %.0f 分钟，跳过转写，仅记录文件路径。",
            duration / 60,
            MAX_TRANSCRIBE_MINUTES,
        )
        mark_skipped(path)
        return

    if MIN_TRANSCRIBE_SECONDS > 0 and duration is not None and duration < MIN_TRANSCRIBE_SECONDS:
        logger.info(
            "文件时长 %.1fs 低于阈值 %.0fs，跳过转写: %s",
            duration, MIN_TRANSCRIBE_SECONDS, path.name,
        )
        mark_skipped(path)
        return

    last_error = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            _process_once(path)
            mark_success(path)
            if _check_missed:
                _check_today_files()
            return
        except EmptyTranscriptionError:
            mark_skipped(path)
            logger.info("转写为空，已跳过（不重试）: %s", path.name)
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
    try:
        ensure_directory_readable(Path(VOICE_MEMOS_DIR), "Voice Memos 监听目录")
        journal_probe_date = datetime.now()
        ensure_directory_readable(Path(os.getenv("OBSIDIAN_JOURNAL_DIR", "")).expanduser(), "Obsidian 日记目录")
        from listen_watch.obsidian import _journal_path
        ensure_file_read_write(_journal_path(journal_probe_date), "当天 Obsidian 日记文件")
    except (PermissionError, FileNotFoundError) as e:
        logger.warning("启动校验未通过（将在运行中重试）: %s", e)

    # 补处理启动前遗漏的文件
    missed = get_unprocessed(Path(VOICE_MEMOS_DIR))
    if missed:
        logger.info("发现 %d 个未处理文件，开始补处理...", len(missed))
        for p in missed:
            on_new_memo(p)

    watcher = VoiceMemoWatcher(VOICE_MEMOS_DIR, on_new_memo)
    watcher.run_forever()
    logger.info("listen_watch 已退出")
