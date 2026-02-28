# PRD · listen_watch

## 1. 项目概述

`listen_watch` 是一个运行在 Mac 上的后台守护进程。它持续监听 Voice Memos 的 iCloud 同步目录，当检测到新的录音文件时，自动完成：语音转写 → AI 结构化处理 → 追加写入 Obsidian 日记。

---

## 2. 用户场景

用户在 iPhone 上录制语音备忘录（中文为主），iCloud 将音频文件同步到 Mac 本地目录。`listen_watch` 自动检测新文件，将其转写并整理为结构化笔记，追加到 Obsidian 当天日记文件的「语音记录」章节中。

---

## 3. 核心流程

```
iPhone 录音
    ↓ iCloud 同步
Mac 本地目录（Voice Memos）
    ↓ 文件监听（watchdog）
检测到新 .m4a 文件
    ↓ 豆包语音 API
语音转写文本
    ↓ Claude API
AI 结构化处理
    ↓ 写入文件
Obsidian 当天日记 · 「语音记录」章节
```

---

## 4. 功能需求

### 4.1 文件监听

- 监听目录：`~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/`
- 监听文件类型：`.m4a`
- 触发条件：检测到新文件创建（`on_created` 事件）
- 等待策略：文件创建后等待写入完成（检测文件大小稳定），再开始处理，避免读取未完成的文件

### 4.2 语音转写

- 服务：火山引擎豆包语音大模型 API
- 主要语言：中文（`zh-CN`）
- 输入：`.m4a` 音频文件
- 输出：原始转写文本字符串

### 4.3 AI 处理

#### 支持的 AI 服务

| 阶段 | 服务 | 说明 |
|------|------|------|
| **MVP** | Kimi（月之暗面） | 中文能力强，国内延迟低 |
| 后续扩展 | DeepSeek | 价格极低，适合长文本处理 |
| 后续扩展 | Claude（Anthropic） | 结构化理解和中文整理能力最强 |

#### 切换机制

- **主服务**：通过 `.env` 中的 `AI_PROVIDER` 指定（`kimi` / `deepseek` / `claude`）
- **备用服务**：通过 `AI_FALLBACK_PROVIDER` 指定，主服务连续失败后自动切换
- 代码层面使用统一的 `AIProcessor` 接口，各服务实现相同的方法，新增服务只需添加一个 Adapter

#### 输入 / 输出

- 输入：原始转写文本
- 输出：包含以下四部分的结构化内容：

  | 字段 | 说明 |
  |------|------|
  | **标题** | 根据内容提炼的简短主题（10 字以内） |
  | **摘要** | 1~3 句话概括核心内容 |
  | **待办事项** | 提取的 action items，格式为 Markdown 任务列表 |
  | **语音转写内容** | 原始的语音转写内容 |

- 若无待办事项，该字段留空不展示

### 4.4 写入 Obsidian

- 目标文件：Obsidian 日记文件夹中以当天日期命名的文件（如 `2026-02-28.md`）
- 目标章节：文件内名为 `## 语音记录` 的二级标题章节
- 写入策略：
  - 若当天文件不存在：**不创建**，记录错误日志，等待用户手动创建后重试
  - 若文件存在但无 `## 语音记录` 章节：**自动在文件末尾追加**该章节
  - 若章节已存在：在章节内末尾**追加**新条目

- 每条语音记录的 Markdown 格式：

```markdown
### HH:MM · {AI 生成标题}

> {摘要}

**待办事项**
- [ ] 事项一
- [ ] 事项二

**整理后内容**
{整理后的文字}
```

### 4.5 已处理文件追踪

- 使用本地 SQLite 数据库（`~/.listen_watch/processed.db`）记录已处理文件
- 记录字段：文件路径、文件大小、处理时间、处理状态
- 每次启动时扫描监听目录，补处理启动前遗漏的新文件

### 4.6 错误处理与重试

- 转写或 AI 处理失败后，自动重试最多 **3 次**（指数退避：5s / 15s / 45s）
- 3 次仍失败则记录错误到日志文件（`~/.listen_watch/error.log`），跳过该文件
- 失败的文件**不标记为已处理**，下次启动时会重新尝试

---

## 5. 运行方式

### 5.1 手动运行

```bash
source .venv/bin/activate
python main.py
```

### 5.2 开机自动启动（launchd）

- 提供 `com.keji.listen-watch.plist` 配置文件
- 安装命令：
  ```bash
  cp com.keji.listen-watch.plist ~/Library/LaunchAgents/
  launchctl load ~/Library/LaunchAgents/com.keji.listen-watch.plist
  ```
- 进程崩溃后由 launchd 自动重启

---

## 6. 配置项（.env）

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `AI_PROVIDER` | 主 AI 服务（`kimi` / `deepseek` / `claude`） | `kimi` |
| `AI_FALLBACK_PROVIDER` | 备用 AI 服务，主服务失败后自动切换 | `deepseek` |
| `KIMI_API_KEY` | Kimi API 密钥 | `sk-...` |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | `sk-...` |
| `ANTHROPIC_API_KEY` | Claude API 密钥 | `sk-ant-...` |
| `VOLCENGINE_API_KEY` | 豆包语音 API 密钥 | `...` |
| `VOLCENGINE_APP_ID` | 豆包语音 App ID | `...` |
| `VOICE_MEMOS_DIR` | Voice Memos 同步目录 | `~/Library/Group Containers/...` |
| `OBSIDIAN_VAULT_DIR` | Obsidian Vault 根目录 | `/Users/xxx/Documents/MyVault` |
| `OBSIDIAN_JOURNAL_FOLDER` | 日记文件夹（相对 Vault） | `Journal` |
| `OBSIDIAN_DATE_FORMAT` | 日记文件名日期格式 | `%Y-%m-%d` |

---

## 7. 项目结构

```
listen_watch/
├── listen_watch/
│   ├── __init__.py
│   ├── watcher.py        # 文件系统监听（watchdog）
│   ├── transcriber.py    # 豆包语音转写
│   ├── processor.py      # AI 处理统一接口 + 各服务 Adapter
│   ├── obsidian.py       # 写入 Obsidian 日记
│   └── db.py             # SQLite 已处理文件追踪
├── main.py               # 入口，启动监听循环
├── com.keji.listen-watch.plist  # launchd 配置
├── requirements.txt
├── .env.example
└── PRD.md
```

---

## 8. 非功能需求

- **资源占用**：空闲时 CPU 占用 < 1%，内存 < 50MB
- **处理延迟**：从文件写入完成到笔记写入 Obsidian，正常情况下 < 60 秒
- **日志**：运行日志输出到 `~/.listen_watch/listen_watch.log`，按天滚动
- **安全**：API Key 仅从 `.env` 读取，不写入任何日志或数据库
