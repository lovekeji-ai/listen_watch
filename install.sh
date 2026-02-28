#!/bin/zsh
# 创建 listen_watch.app 并注册为开机 Login Item
# ⚠ app bundle 只在首次创建时签名；已存在则不重建，避免 TCC 授权失效
# 换机器/重装：删除 listen_watch.app 后重新运行此脚本

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="listen_watch"
APP_PATH="$PROJECT_DIR/$APP_NAME.app"
MACOS_DIR="$APP_PATH/Contents/MacOS"

if [[ -d "$APP_PATH" ]]; then
    echo "→ $APP_NAME.app 已存在，跳过创建（避免 TCC 授权失效）"
else
    echo "→ 编译 launcher ..."
    cc -arch arm64 -arch x86_64 -O2 \
       -o /tmp/listen_watch_launcher "$PROJECT_DIR/launcher.c"

    echo "→ 生成 $APP_NAME.app ..."
    mkdir -p "$MACOS_DIR"
    mv /tmp/listen_watch_launcher "$MACOS_DIR/$APP_NAME"
    chmod +x "$MACOS_DIR/$APP_NAME"

    # Info.plist：LSUIElement=true 让它作为后台应用运行（无 Dock 图标）
    cat > "$APP_PATH/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.keji.listen-watch</string>
    <key>CFBundleName</key>
    <string>listen_watch</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
PLIST

    echo "→ 签名 ..."
    if security find-identity -v -p codesigning 2>/dev/null | grep -q "listen_watch Signing"; then
        codesign --sign "listen_watch Signing" --force "$APP_PATH"
    else
        echo "⚠ 未找到 listen_watch Signing 证书，使用 ad-hoc 签名"
        codesign --sign - --force "$APP_PATH"
    fi

    echo ""
    echo "⚠ 首次安装，需手动完成一步："
    echo "  系统设置 → 隐私与安全性 → 完全磁盘访问权限 → 点 +"
    echo "  选择: $APP_PATH"
    echo "  （之后无需重复，除非删除 listen_watch.app 重建）"
    echo ""
fi

echo "→ 注册为 Login Item ..."
osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$APP_PATH\", hidden:true}" 2>/dev/null \
  && echo "✓ 已添加到登录项" \
  || echo "⚠ 请手动添加：系统设置 → 通用 → 登录项 → 选择 $APP_PATH"

echo "✓ 完成。"
