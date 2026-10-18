#!/bin/bash
# 把 KeyLock 打包成 macOS 的 .app。双击运行，或者：
#   chmod +x build_app.sh && ./build_app.sh
#
# 注意：每次重新打包，.app 的签名都会变，系统会认为是一个新程序 ——
# 「辅助功能」授权需要重新勾一次。开发期建议直接用 run.command 跑源码。

set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "找不到 python3。"
    exit 1
fi

echo "=== 检查依赖 ==="
python3 -c "import tkinter" || { echo "缺少 tkinter，无法打包。"; exit 1; }

if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
    echo "=== 安装 PyInstaller ==="
    python3 -m pip install --user --upgrade pyinstaller
fi

echo
echo "=== 打包 ==="
rm -rf build dist KeyLock.spec
python3 -m PyInstaller \
    --noconfirm --clean \
    --windowed \
    --name KeyLock \
    --osx-bundle-identifier com.keylock.app \
    --hidden-import quartz \
    --hidden-import keyboard_blocker \
    main.py

echo
echo "=== 完成 ==="
echo "产物：$(pwd)/dist/KeyLock.app"
echo
echo "第一次运行请到 系统设置 → 隐私与安全性 → 辅助功能 里勾上 KeyLock。"
