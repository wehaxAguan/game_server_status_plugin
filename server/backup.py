#!/usr/bin/env python3
"""
Windrose 备份模块
- 本地备份存档
- 上传到阿里云 OSS
- 发送飞书通知
"""

import os
import json
import yaml
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

# 加载配置
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

def send_feishu(title: str, content: str):
    """发送飞书消息"""
    webhook = config["feishu"]["webhook"]
    
    try:
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue"
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "plain_text", "content": content}}
                ]
            }
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(webhook, data=data, headers={'Content-Type': 'application/json'})
        response = urllib.request.urlopen(req, timeout=10)
        return response.status == 200
    except Exception as e:
        print(f"飞书发送失败: {e}")
        return False

def do_backup(reason: str = "manual"):
    """执行备份"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    backup_name = f"windrose-save-{timestamp}.zip"
    backup_dir = Path(config["windrose"]["backup_dir"])
    backup_file = backup_dir / backup_name
    
    # 创建备份目录
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    # 清理超过 7 天的旧备份
    for old_backup in backup_dir.glob("windrose-save-*.zip"):
        if old_backup.stat().st_mtime < datetime.now().timestamp() - 7 * 24 * 3600:
            old_backup.unlink()
    
    print(f"[{timestamp}] 开始备份: {reason}")
    
    # 清理临时目录
    temp_dir = Path("C:\\windrose-backup-temp")
    if temp_dir.exists():
        subprocess.run(["Remove-Item", str(temp_dir), "-Recurse", "-Force"], 
                       shell=True, capture_output=True)
    
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # 复制存档文件 (使用 robocopy)
    save_path = config["windrose"]["save_path"]
    subprocess.run([
        "robocopy", save_path, str(temp_dir / "Saved"),
        "/E", "/R:0", "/W:0", "/NP", "/MT:4"
    ], shell=True, capture_output=True)
    
    # 复制服务器描述
    server_desc = Path(save_path).parent / "ServerDescription.json"
    if server_desc.exists():
        subprocess.run(["Copy-Item", str(server_desc), str(temp_dir), "-Force"],
                       shell=True, capture_output=True)
    
    # 压缩
    subprocess.run([
        "Compress-Archive", 
        "-Path", str(temp_dir / "*"),
        "-DestinationPath", str(backup_file),
        "-Force", "-CompressionLevel", "Fastest"
    ], shell=True, capture_output=True)
    
    # 清理临时目录
    if temp_dir.exists():
        subprocess.run(["Remove-Item", str(temp_dir), "-Recurse", "-Force"],
                       shell=True, capture_output=True)
    
    # 检查备份文件
    if not backup_file.exists():
        send_feishu("⚠️ Windrose 备份失败", f"时间: {timestamp}\n原因: {reason}\n错误: 文件不存在")
        return {"success": False, "error": "backup file not created"}
    
    size_mb = backup_file.stat().st_size / (1024 * 1024)
    print(f"[{timestamp}] 备份完成: {size_mb:.2f} MB")
    
    # 上传到 OSS
    oss_result = upload_to_oss(backup_file, backup_name)
    
    # 发送飞书通知
    if oss_result["success"]:
        content = f"时间: {timestamp}\n触发原因: {reason}\n文件: {backup_name}\n大小: {size_mb:.2f} MB\nOSS: ✓ 已上传"
    else:
        content = f"时间: {timestamp}\n触发原因: {reason}\n文件: {backup_name}\n大小: {size_mb:.2f} MB\nOSS: ✗ 上传失败 ({oss_result.get('error')})"
    
    send_feishu("💾 Windrose 备份完成", content)
    
    return {
        "success": True,
        "filename": backup_name,
        "size_mb": round(size_mb, 2),
        "oss": oss_result,
        "path": str(backup_file)
    }

def upload_to_oss(file_path: Path, filename: str):
    """上传备份到阿里云 OSS"""
    bucket = config["oss"]["bucket"]
    endpoint = config["oss"]["endpoint"]
    prefix = config["oss"]["prefix"]
    
    # OSS 对象路径
    oss_path = f"{prefix}{filename}"
    
    # 使用 aliyun CLI 上传
    try:
        # 首先检查 aliyun CLI 是否可用
        result = subprocess.run(
            ["aliyun", "oss", "cp", str(file_path), f"oss://{bucket}/{oss_path}"],
            capture_output=True,
            text=True,
            timeout=300  # 5 分钟超时
        )
        
        if result.returncode == 0:
            return {"success": True, "oss_path": oss_path}
        else:
            return {"success": False, "error": result.stderr}
    
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "upload timeout"}
    except FileNotFoundError:
        return {"success": False, "error": "aliyun CLI not installed"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_oss_backups():
    """列出 OSS 上的备份文件"""
    bucket = config["oss"]["bucket"]
    prefix = config["oss"]["prefix"]
    
    try:
        result = subprocess.run(
            ["aliyun", "oss", "ls", f"oss://{bucket}/{prefix}"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return {"success": False, "error": result.stderr}
        
        # 解析输出
        backups = []
        for line in result.stdout.split('\n'):
            if 'windrose-save-' in line and '.zip' in line:
                parts = line.split()
                if len(parts) >= 4:
                    backups.append({
                        "path": parts[-1],
                        "size": parts[-2] if len(parts) >= 5 else "unknown",
                        "date": parts[0] if len(parts) >= 1 else "unknown"
                    })
        
        return {"success": True, "backups": backups}
    
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    # 测试备份
    import sys
    
    reason = sys.argv[1] if len(sys.argv) > 1 else "manual"
    result = do_backup(reason)
    
    print(json.dumps(result, indent=2, ensure_ascii=False))