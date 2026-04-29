#!/usr/bin/env python3
"""
Windrose 客户端监控脚本
运行在 Mac 上，定时查询 Windows API，处理通知和备份触发
"""

import json
import yaml
import requests
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

# 加载配置
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

# 扩展路径
LOCAL_BACKUP_DIR = Path(config["local"]["backup_dir"].replace("~", str(Path.home())))
STATE_FILE = Path(config["local"]["state_file"].replace("~", str(Path.home())))

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

def query_api(endpoint: str = "/status"):
    """查询 Windows API"""
    host = config["server"]["host"]
    port = config["server"]["port"]
    timeout = config["server"]["timeout"]
    
    url = f"http://{host}:{port}{endpoint}"
    
    try:
        response = requests.get(url, timeout=timeout)
        return {"success": True, "data": response.json()}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "timeout"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "connection_failed"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def trigger_backup(reason: str = "player_offline"):
    """触发 Windows 端备份"""
    host = config["server"]["host"]
    port = config["server"]["port"]
    timeout = 60  # 备份触发可能需要更长时间
    
    url = f"http://{host}:{port}/backup/trigger"
    
    try:
        response = requests.post(url, json={"reason": reason}, timeout=timeout)
        return {"success": True, "data": response.json()}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def update_server_state(players: int):
    """更新服务器端状态"""
    host = config["server"]["host"]
    port = config["server"]["port"]
    
    url = f"http://{host}:{port}/state/update"
    
    try:
        requests.post(url, json={"players": players}, timeout=10)
    except:
        pass  # 状态更新失败不阻塞主流程

def load_state():
    """加载本地状态"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    
    return {"last_players": 0, "last_status": None}

def save_state(state: dict):
    """保存本地状态"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def download_from_oss(oss_path: str, local_path: Path):
    """从 OSS 下载备份文件"""
    bucket = config["oss"]["bucket"]
    
    try:
        result = subprocess.run(
            ["aliyun", "oss", "cp", f"oss://{bucket}/{oss_path}", str(local_path)],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        return result.returncode == 0
    except Exception as e:
        print(f"OSS 下载失败: {e}")
        return False

def sync_backups():
    """同步 OSS 备份到本地"""
    LOCAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    # 查询 OSS 上的备份列表
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
            return
        
        # 解析并下载缺失的备份
        for line in result.stdout.split('\n'):
            if 'windrose-save-' in line and '.zip' in line:
                parts = line.split()
                oss_path = parts[-1].replace(f"oss://{bucket}/", "")
                filename = Path(oss_path).name
                
                local_file = LOCAL_BACKUP_DIR / filename
                
                if not local_file.exists():
                    print(f"下载: {filename}")
                    download_from_oss(oss_path, local_file)
    
    except Exception as e:
        print(f"同步失败: {e}")

def main():
    """主监控逻辑"""
    state = load_state()
    
    # 1. 查询服务器状态
    result = query_api("/status")
    
    if not result["success"]:
        # API 查询失败
        error = result["error"]
        
        if error == "connection_failed" or error == "timeout":
            # 可能是服务器宕机或网络问题
            if state.get("last_status") == "running":
                send_feishu("⚠️ Windrose API 无法连接", 
                           f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                           f"错误: {error}\n"
                           f"服务器可能已停止或网络异常")
        
        save_state({"last_players": state.get("last_players", 0), "last_status": "unknown"})
        return
    
    data = result["data"]
    
    # 2. 检查进程状态
    proc = data.get("process", {})
    if not proc.get("running", False):
        # 服务器进程停止
        send_feishu("🚨 Windrose 服务器已停止",
                   f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                   f"进程状态: 未运行\n"
                   f"请检查服务器！")
        
        # 如果之前有玩家在线，触发备份
        if state.get("last_players", 0) > 0:
            backup_result = trigger_backup("server_stopped_with_players")
            if backup_result.get("success"):
                sync_backups()  # 同步备份到本地
        
        save_state({"last_players": 0, "last_status": "stopped"})
        return
    
    # 3. 检查玩家数量变化
    current_players = data.get("players", 0)
    last_players = state.get("last_players", 0)
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
          f"状态: running | 玩家: {current_players} (上次: {last_players}) | "
          f"内存: {proc.get('memory_gb', 0)} GB")
    
    # 玩家从 >0 → 0，触发备份
    if last_players > 0 and current_players == 0:
        print("玩家离线，触发备份...")
        
        backup_result = trigger_backup("player_offline")
        
        if backup_result.get("success"):
            # 同步备份到本地
            sync_backups()
        else:
            send_feishu("⚠️ Windrose 备份触发失败",
                       f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                       f"错误: {backup_result.get('error')}")
    
    # 4. 更新状态
    update_server_state(current_players)
    save_state({"last_players": current_players, "last_status": "running"})

if __name__ == "__main__":
    # 确保本地备份目录存在
    LOCAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    main()