import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)

WATCH_EXTENSIONS = {".m4a", ".mp4", ".caf"}
# 文件大小稳定判断：连续两次检查大小不变则认为写入完成
FILE_STABLE_CHECK_INTERVAL = 2  # 秒
FILE_STABLE_MAX_WAIT = 60       # 最长等待秒数


def _wait_until_stable(path: Path) -> bool:
    """等待文件写入完成（大小稳定）。返回 True 表示稳定，False 表示超时。"""
    prev_size = -1
    waited = 0
    while waited < FILE_STABLE_MAX_WAIT:
        try:
            current_size = path.stat().st_size
        except FileNotFoundError:
            return False
        if current_size > 0 and current_size == prev_size:
            return True
        prev_size = current_size
        time.sleep(FILE_STABLE_CHECK_INTERVAL)
        waited += FILE_STABLE_CHECK_INTERVAL
    logger.warning("文件写入等待超时: %s", path)
    return False


class VoiceMemoHandler(FileSystemEventHandler):
    def __init__(self, callback):
        """
        callback: 接收一个 Path 参数，在新录音文件就绪后被调用
        """
        super().__init__()
        self.callback = callback

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in WATCH_EXTENSIONS:
            return
        logger.info("检测到新文件: %s", path.name)
        if _wait_until_stable(path):
            logger.info("文件写入完成，开始处理: %s", path.name)
            try:
                self.callback(path)
            except Exception as e:
                logger.error("处理文件时发生错误 %s: %s", path.name, e, exc_info=True)
        else:
            logger.warning("跳过未稳定文件: %s", path.name)


class VoiceMemoWatcher:
    def __init__(self, watch_dir: str, callback):
        self.watch_dir = Path(watch_dir).expanduser()
        self.callback = callback
        self._observer = None

    def start(self):
        if not self.watch_dir.exists():
            raise FileNotFoundError(f"监听目录不存在: {self.watch_dir}")
        handler = VoiceMemoHandler(self.callback)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_dir), recursive=False)
        self._observer.start()
        logger.info("开始监听: %s", self.watch_dir)

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("监听已停止")

    def run_forever(self):
        """阻塞运行，直到 KeyboardInterrupt。"""
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
