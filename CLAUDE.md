# listen_watch — Claude 项目指南

## 项目概述
macOS 后台守护进程：监听 Voice Memos iCloud 同步目录 → 豆包语音转写 → AI 结构化处理 → 追加写入 Obsidian 日记

GitHub: https://github.com/lovekeji-ai/listen_watch

## 技术栈
- Python 3.9，虚拟环境在 `.venv/`
- 文件监听：watchdog
- 语音转写：火山引擎豆包语音 API（`/api/v3/auc/bigmodel`）
  - 本地文件先上传阿里云 OSS，取签名 URL 传给豆包，转写完删除
- AI 处理：统一接口 + Adapter 模式（Kimi MVP，DeepSeek/Claude 备用）
  - 切换：`.env` 中 `AI_PROVIDER` / `AI_FALLBACK_PROVIDER`
  - Kimi 使用模型：`kimi-k2-0711-preview`
- Obsidian 写入：直接操作 Markdown 文件
- 已处理追踪：SQLite（`~/.listen_watch/processed.db`）
- 运行方式：手动（`python main.py`）或 launchd（`install.sh`）

## 关键文件
- `main.py` — 入口，含日志配置、重试逻辑、启动补处理
- `listen_watch/watcher.py` — watchdog 文件监听，等待文件写入稳定
- `listen_watch/transcriber.py` — OSS 上传 + 豆包转写 + OSS 清理
- `listen_watch/processor.py` — AI 处理，返回 `ProcessedMemo` dataclass
- `listen_watch/obsidian.py` — 写入日记，插入 `## 语音记录` 章节
- `listen_watch/db.py` — SQLite 追踪，含转写/AI 结果缓存
- `.env.example` — 所有配置项模板（含中文注释）
- `com.keji.listen-watch.plist.example` — launchd 配置模板
- `install.sh` — 生成 plist 并安装 launchd 服务

## ProcessedMemo 结构
```python
@dataclass
class ProcessedMemo:
    title: str          # AI 生成标题（≤10字）
    summary: str        # 摘要（1-3句）
    todos: List[str]    # 待办事项（无则空列表）
    cleaned_text: str   # 整理后内容（不写入 Obsidian）
    original_text: str  # 原始转写文本（由调用方填入）
    memo_title: str     # iOS 录音标题如"录音 53"（由调用方填入）
```

## Obsidian 写入规则
- 目标：`OBSIDIAN_JOURNAL_DIR` 下以当天日期命名的 `.md` 文件
- 日记文件不存在：调用 `ensure_journal_exists()` 自动创建（见下）
- 写入位置：`## 语音记录` 章节内，`---` 分隔线之前
- 章节不存在：自动在文件末尾创建
- 每条记录格式：
  ```
  ### HH:MM · {iOS录音标题} · {AI生成标题}
  > 摘要
  **待办事项**（无则省略）
  - [ ] ...
  **原始转写**
  {原始转写文字}
  ```

## 自动创建日记（ensure_journal_exists）
日记文件不存在时，`obsidian.py` 的 `ensure_journal_exists()` 按以下顺序处理：
1. 调用 `open "obsidian://daily-notes?vault=<VaultName>"` 触发 Obsidian 内置 Daily Notes 插件
   - Vault 名称从 `OBSIDIAN_VAULT_DIR` 路径末段自动推导，无需额外配置
2. 轮询等待最多 10 秒（每 0.5s 检查一次）让 Obsidian 创建文件
3. 超时或 URI 失败 → 兜底创建最简 `# YYYY-MM-DD\n\n` 格式文件
- 前提：Obsidian 处于运行状态时优先走插件路径（保留模板等设置）；未运行时直接走兜底

## 数据库 Schema
`~/.listen_watch/processed.db` 表 `processed_files`：
- `file_path` — 文件绝对路径（唯一键）
- `file_size` — 文件大小（字节）
- `status` — `success` / `failed` / `pending`
- `processed_at` — 处理时间
- `transcription_text` — 豆包转写结果缓存
- `ai_result_json` — ProcessedMemo JSON 缓存
- `memo_title` — iOS 语音备忘录显示标题
- `duration_seconds` — 录音时长（秒）

## 错误处理
- 重试：最多 3 次，指数退避（5s / 15s / 45s）
- 重试时复用缓存：转写和 AI 结果已缓存则跳过，只重试写 Obsidian
- 日志：`~/.listen_watch/listen_watch.log` 和 `error.log`（各保留 15 天）

## 注意事项
- `.env` 含 API Key，已在 `.gitignore` 中，不得提交
- `com.keji.listen-watch.plist` 含本机路径，已在 `.gitignore` 中，用 `install.sh` 生成
- launchd 运行时需要给 `/usr/bin/python3` 授予「完全磁盘访问权限」
- 豆包 API submit 接口正常返回空 `{}`，不是错误
- Python 3.9 不支持 `X | Y` 类型注解，需用 `Optional[X]`
