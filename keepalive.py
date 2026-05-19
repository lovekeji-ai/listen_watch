#!/usr/bin/env python3
"""
listen_watch keepalive 脚本
launchd 每小时调用：触发 VoiceMemos iCloud 同步，并检查主进程是否存活，未运行则拉起 listen_watch.app。
注意：文件名不能叫 watchdog.py，否则会遮蔽同名 pip 库导致 main.py 启动失败。
"""
import subprocess
import logging
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
APP_PATH = PROJECT_DIR / "listen_watch.app"
LOG_DIR = Path.home() / ".listen_watch"

LOG_DIR.mkdir(exist_ok=True)
# launchd 已将 stdout 重定向到 watchdog.log，只用 StreamHandler 避免重复写入
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] watchdog: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def trigger_sync():
    """后台激活 VoiceMemos，触发 iCloud CloudKit 同步"""
    subprocess.Popen(["open", "-g", "-b", "com.apple.VoiceMemos"])
    log.info("已触发 VoiceMemos iCloud 同步")


def is_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", "listen_watch/main.py"],
        capture_output=True,
    )
    return result.returncode == 0


def main():
    trigger_sync()

    if is_running():
        log.info("进程存活，无需操作")
        return

    log.warning("进程未运行，正在拉起...")
    if not APP_PATH.exists():
        log.error(f"App 不存在: {APP_PATH}，请先运行 install.sh")
        sys.exit(1)

    subprocess.Popen(["open", str(APP_PATH)])
    log.info("已发送启动指令")


if __name__ == "__main__":
    main()
