#!/bin/bash
# Windrose 客户端部署脚本
# 在 Mac 上运行

WORK_DIR="$HOME/workbench/game_server_status_plugin"

echo "=== Windrose 客户端部署 ==="

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "Python3 未安装"
    exit 1
fi

# 安装依赖
echo "安装 Python 依赖..."
pip3 install -r "$WORK_DIR/client/requirements.txt" --quiet

# 检查阿里云 CLI
if ! command -v aliyun &> /dev/null; then
    echo "阿里云 CLI 未安装"
    echo "安装: brew install aliyun-cli"
    exit 1
fi

# 创建本地备份目录
mkdir -p ~/windrose-backups

# 创建 launchd 定时任务
PLIST_PATH="$HOME/Library/LaunchAgents/com.user.windrose-monitor.plist"

cat > "$PLIST_PATH" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.windrose-monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>WORK_DIR/client/monitor.py</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>StandardOutPath</key>
    <string>/tmp/windrose-monitor.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/windrose-monitor.err</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
PLIST_EOF

# 替换路径
sed -i '' "s|WORK_DIR|$WORK_DIR|g" "$PLIST_PATH"

# 加载定时任务
launchctl unload "$PLIST_PATH" 2>/dev/null
launchctl load "$PLIST_PATH"

echo "定时任务已创建 (每 5 分钟)"

# 测试 API 连接
echo ""
echo "测试 API 连接..."
python3 "$WORK_DIR/client/monitor.py"

echo ""
echo "=== 部署完成 ==="
echo "监控脚本将每 5 分钟运行一次"
echo "日志: /tmp/windrose-monitor.log"