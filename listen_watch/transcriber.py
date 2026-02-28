import os
import uuid
import time
import logging
import requests
import oss2
from pathlib import Path

logger = logging.getLogger(__name__)

# --- 豆包语音配置 ---
VOLCENGINE_APP_ID = os.getenv("VOLCENGINE_APP_ID", "")
VOLCENGINE_API_KEY = os.getenv("VOLCENGINE_API_KEY", "")
VOLCENGINE_RESOURCE_ID = os.getenv("VOLCENGINE_RESOURCE_ID", "volc.bigasr.auc")

SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

CODE_SUCCESS = 20000000
CODE_PROCESSING = 20000001

POLL_INTERVAL = 3    # 轮询间隔（秒）
POLL_MAX_WAIT = 300  # 最长等待时间（秒）

# --- 阿里云 OSS 配置 ---
OSS_ACCESS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET", "")
OSS_BUCKET_NAME = os.getenv("OSS_BUCKET_NAME", "")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "")
OSS_TEMP_PREFIX = os.getenv("OSS_TEMP_PREFIX", "listen_watch_tmp/")

# 签名 URL 有效期（秒），足够豆包服务器下载即可
OSS_URL_EXPIRES = 3600


def _oss_bucket() -> oss2.Bucket:
    auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)


def _upload_to_oss(path: Path) -> tuple[str, str]:
    """上传文件到 OSS，返回 (oss_key, 签名URL)。"""
    oss_key = f"{OSS_TEMP_PREFIX}{uuid.uuid4().hex}{path.suffix}"
    bucket = _oss_bucket()
    bucket.put_object_from_file(oss_key, str(path))
    signed_url = bucket.sign_url("GET", oss_key, OSS_URL_EXPIRES)
    logger.debug("OSS 上传完成: %s", oss_key)
    return oss_key, signed_url


def _delete_from_oss(oss_key: str) -> None:
    """删除 OSS 临时文件，失败仅记录警告不抛出。"""
    try:
        _oss_bucket().delete_object(oss_key)
        logger.debug("OSS 临时文件已删除: %s", oss_key)
    except Exception as e:
        logger.warning("删除 OSS 临时文件失败 %s: %s", oss_key, e)


def _make_headers(request_id: str) -> dict:
    return {
        "X-Api-App-Key": VOLCENGINE_APP_ID,
        "X-Api-Access-Key": VOLCENGINE_API_KEY,
        "X-Api-Resource-Id": VOLCENGINE_RESOURCE_ID,
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
        "Content-Type": "application/json",
    }


def _submit(audio_url: str, request_id: str) -> None:
    """提交转写任务。"""
    payload = {
        "user": {"uid": "listen_watch"},
        "audio": {
            "url": audio_url,
            "format": "m4a",
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
        },
    }
    resp = requests.post(SUBMIT_URL, json=payload, headers=_make_headers(request_id), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # 豆包 submit 接口正常返回空 {}，有 resp.code 时才检查错误
    if data:
        code = int(data.get("resp", {}).get("code", CODE_SUCCESS))
        if code not in (CODE_SUCCESS, CODE_PROCESSING):
            raise RuntimeError(f"提交转写任务失败: {data}")


def _poll(request_id: str) -> str:
    """轮询直到转写完成，返回转写文本。"""
    headers = _make_headers(request_id)
    waited = 0
    while waited < POLL_MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
        resp = requests.post(QUERY_URL, json={}, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # result.text 存在即转写完成
        if data.get("result", {}).get("text") is not None:
            return data["result"]["text"]
        code = int(data.get("resp", {}).get("code", CODE_PROCESSING))
        if code == CODE_PROCESSING:
            logger.debug("转写进行中... (%ds)", waited)
            continue
        raise RuntimeError(f"转写失败: {data}")
    raise TimeoutError(f"转写超时（>{POLL_MAX_WAIT}s）")


def transcribe(path: Path) -> str:
    """
    主入口：上传音频到 OSS → 提交豆包转写 → 轮询结果 → 删除 OSS 临时文件。
    返回转写文本，失败时抛出异常。
    """
    oss_key = None
    try:
        logger.info("上传音频到 OSS: %s", path.name)
        oss_key, signed_url = _upload_to_oss(path)

        request_id = str(uuid.uuid4())
        logger.info("提交转写任务 (request_id=%s)", request_id)
        _submit(signed_url, request_id)

        logger.info("等待转写结果...")
        text = _poll(request_id)
        logger.info("转写完成，共 %d 字", len(text))
        return text
    finally:
        if oss_key:
            _delete_from_oss(oss_key)
