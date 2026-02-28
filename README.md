# listen_watch

macOS 后台守护进程：自动监听 Voice Memos iCloud 同步目录，完成语音转写、AI 结构化处理，并追加写入 Obsidian 当天日记。

## 工作流程

```
iPhone / Watch 录音
    ↓ iCloud 同步
Mac 本地目录（Voice Memos）
    ↓ watchdog 文件监听
检测到新 .m4a 文件
    ↓ 上传阿里云 OSS → 豆包语音 API
语音转写文本
    ↓ Kimi / DeepSeek / Claude
AI 结构化处理（标题、摘要、待办事项）
    ↓ 写入文件
Obsidian 当天日记 · 「语音记录」章节
```

## 环境要求

- macOS
- Python 3.9+

## 安装

```bash
# 克隆项目
git clone https://github.com/lovekeji-ai/listen_watch.git
cd listen_watch

# 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入各项 API Key 和路径
```

## 配置

复制 `.env.example` 为 `.env` 并填写以下内容：

| 变量 | 说明 |
|------|------|
| `VOICE_MEMOS_DIR` | Voice Memos iCloud 同步目录 |
| `OBSIDIAN_JOURNAL_DIR` | Obsidian 日记文件夹绝对路径 |
| `VOLCENGINE_APP_ID` | 豆包语音 App ID |
| `VOLCENGINE_API_KEY` | 豆包语音 Access Token |
| `OSS_ACCESS_KEY_ID` | 阿里云 OSS AccessKey ID |
| `OSS_ACCESS_KEY_SECRET` | 阿里云 OSS AccessKey Secret |
| `OSS_BUCKET_NAME` | OSS Bucket 名称 |
| `OSS_ENDPOINT` | OSS Endpoint（如 `oss-cn-hangzhou.aliyuncs.com`）|
| `AI_PROVIDER` | 主 AI 服务：`kimi` / `deepseek` / `claude` |
| `KIMI_API_KEY` | Kimi API 密钥 |
| `MAX_TRANSCRIBE_MINUTES` | 超过此时长（分钟）的录音跳过转写，`0` 不限制 |

## 手动运行

```bash
source .venv/bin/activate
python main.py
```

## 开机自启（launchd）

```bash
chmod +x install.sh
./install.sh
```

查看服务状态：

```bash
launchctl list | grep keji
```

停止服务：

```bash
launchctl unload ~/Library/LaunchAgents/com.keji.listen-watch.plist
```

## 日志与数据

| 路径 | 说明 |
|------|------|
| `~/.listen_watch/listen_watch.log` | 运行日志（15 天滚动） |
| `~/.listen_watch/error.log` | 错误日志（15 天滚动） |
| `~/.listen_watch/processed.db` | 已处理文件记录（SQLite） |

## Obsidian 写入格式

```markdown
### HH:MM · 录音标题 · AI 生成标题

> 摘要

**待办事项**
- [ ] 事项一

**原始转写**
原始语音转写内容
```
