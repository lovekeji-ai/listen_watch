# listen_watch

A macOS background daemon that monitors Voice Memos sync, transcribes audio with Whisper, processes it with Claude AI, and saves the result as Obsidian notes.

## Workflow

```
Voice Memos (sync) → File Watcher → Whisper (STT) → Claude (AI) → Obsidian (.md)
```

## Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys and paths
```

## Configuration

Copy `.env.example` to `.env` and fill in:

- `ANTHROPIC_API_KEY` — Claude API key
- `VOICE_MEMOS_DIR` — Path to Voice Memos sync folder
- `OBSIDIAN_VAULT_DIR` — Path to your Obsidian vault

## Usage

```bash
python main.py
```
