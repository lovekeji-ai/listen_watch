#!/bin/zsh
# 生成 launchd plist 并安装为开机自启服务

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.keji.listen-watch.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo "→ 生成 $PLIST_NAME ..."
sed "s|YOUR_HOME|$HOME|g" "$PROJECT_DIR/$PLIST_NAME.example" > "$PROJECT_DIR/$PLIST_NAME"

echo "→ 安装到 $LAUNCH_AGENTS ..."
mkdir -p "$LAUNCH_AGENTS"
cp "$PROJECT_DIR/$PLIST_NAME" "$LAUNCH_AGENTS/$PLIST_NAME"

# 若已加载则先卸载
launchctl unload "$LAUNCH_AGENTS/$PLIST_NAME" 2>/dev/null || true

echo "→ 启动服务 ..."
launchctl load "$LAUNCH_AGENTS/$PLIST_NAME"

echo "✓ 安装完成。查看状态："
echo "  launchctl list | grep keji"
