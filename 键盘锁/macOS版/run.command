#!/bin/bash
# KeyLock 启动脚本（macOS）。双击运行，或者：
#   chmod +x run.command && ./run.command
#
# 从 Finder 双击时工作目录是家目录，所以这里先切到脚本自己所在的位置。

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "找不到 python3。请先安装 Python 3（python.org 的官方安装包自带 tkinter）。"
    read -r -p "按回车关闭…" _
    exit 1
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "这个 python3 没有 tkinter。"
    echo "如果用 Homebrew 装的：brew install python-tk"
    echo "或者去 python.org 下载官方安装包。"
    read -r -p "按回车关闭…" _
    exit 1
fi

python3 main.py "$@"
status=$?

# 双击运行时窗口会随进程结束而消失，非正常退出就停一下让人看清报错
if [ $status -ne 0 ]; then
    echo
    echo "KeyLock 退出码：$status"
    read -r -p "按回车关闭…" _
fi
exit $status
