"""本地 Whisper 兜底转写：spawn 一个装有 faster-whisper 的 Python 解释器跑转写。

设计要点：
- 通过环境变量配置，绝对路径放在 .env，代码里不出现机器特定路径
- 跨解释器：listen_watch 本体的 venv 没装 faster-whisper，靠 subprocess 调用配置好的外部解释器
"""
import os
import subprocess
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _config() -> Optional[dict]:
    """读取本地 whisper 配置。未配置解释器路径时返回 None，调用方据此决定是否启用兜底。"""
    py = os.getenv("LOCAL_WHISPER_PYTHON", "").strip()
    if not py:
        return None
    return {
        "python": py,
        "model": os.getenv("LOCAL_WHISPER_MODEL", "large-v3").strip(),
        "language": os.getenv("LOCAL_WHISPER_LANGUAGE", "zh").strip() or None,
        "timeout": int(os.getenv("LOCAL_WHISPER_TIMEOUT", "600")),
    }


def is_enabled() -> bool:
    return _config() is not None


# 在子进程里执行的脚本：只 print 最终文本到 stdout，日志写 stderr
_RUNNER = r"""
import sys
from faster_whisper import WhisperModel
audio_path = sys.argv[1]
model_name = sys.argv[2]
language = sys.argv[3] or None
print(f"[whisper] loading model={model_name}", file=sys.stderr, flush=True)
model = WhisperModel(model_name)
print(f"[whisper] transcribing {audio_path} language={language}", file=sys.stderr, flush=True)
segments, info = model.transcribe(audio_path, language=language)
parts = []
for seg in segments:
    parts.append(seg.text)
sys.stdout.write("".join(parts).strip())
print(f"[whisper] done duration={info.duration:.1f}s", file=sys.stderr, flush=True)
"""


def transcribe(path: Path) -> str:
    """同步调用本地 whisper。失败抛异常；返回字符串（可能为空）。"""
    cfg = _config()
    if cfg is None:
        raise RuntimeError("LOCAL_WHISPER_PYTHON 未配置，无法启用本地兜底")
    if not Path(cfg["python"]).exists():
        raise FileNotFoundError(f"LOCAL_WHISPER_PYTHON 路径不存在: {cfg['python']}")

    logger.info("本地 whisper 转写: %s (model=%s)", path.name, cfg["model"])
    proc = subprocess.run(
        [cfg["python"], "-c", _RUNNER, str(path), cfg["model"], cfg["language"] or ""],
        capture_output=True,
        text=True,
        timeout=cfg["timeout"],
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"本地 whisper 失败 (returncode={proc.returncode}): {proc.stderr.strip()[-500:]}"
        )
    if proc.stderr.strip():
        for line in proc.stderr.strip().splitlines():
            logger.debug("whisper stderr: %s", line)
    text = proc.stdout.strip()
    logger.info("本地 whisper 完成，共 %d 字", len(text))
    return text
