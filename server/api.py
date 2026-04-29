#!/usr/bin/env python3
"""
Windrose Server Status API
运行在 Windows 服务器上，提供状态查询和备份触发接口
"""

import os
import json
import yaml
import psutil
import re
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, request

app = Flask(__name__)

# 加载配置
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

def get_process_status():
    """获取 Windrose 进程状态"""
    process_name = config["windrose"]["process_name"]
    
    for proc in psutil.process_iter(['name', 'pid', 'memory_info']):
        try:
            if process_name.lower() in proc.info['name'].lower():
                return {
                    "running": True,
                    "pid": proc.info['pid'],
                    "memory_mb": round(proc.info['memory_info'].rss / (1024 * 1024), 2),
                    "memory_gb": round(proc.info['memory_info'].rss / (1024 * 1024 * 1024), 2)
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    return {"running": False, "pid": None, "memory_mb": 0, "memory_gb": 0}

def get_player_count():
    """解析日志获取玩家数量"""
    log_path = Path(config["windrose"]["log_path"])
    
    if not log_path.exists():
        return {"count": -1, "error": "log file not found"}
    
    try:
        # 读取最后 3000 行
        with open(log_path, 'r', errors='ignore') as f:
            lines = f.readlines()[-3000:]
    except Exception as e:
        return {"count": -1, "error": str(e)}
    
    sessions = {}
    
    for line in lines:
        # 提取 session ID (32位十六进制)
        match = re.search(r'BLPlayerSessionId\s*([a-f0-9]{32})', line)
        if not match:
            continue
        
        session_id = match.group(1)
        
        # 玩家连接
        if 'AddPlayer' in line and 'AccountId' in line:
            if sessions.get(session_id, {}).get('status') != 'disconnected':
                sessions[session_id] = {'status': 'connected'}
        
        # 玩家断开
        elif 'disconnected' in line.lower() or 'OnAccountDisconnected' in line:
            sessions[session_id] = {'status': 'disconnected'}
    
    # 统计在线玩家
    online = sum(1 for s in sessions.values() if s['status'] == 'connected')
    return {"count": online, "sessions": len(sessions)}

def get_last_backup():
    """获取最新备份信息"""
    backup_dir = Path(config["windrose"]["backup_dir"])
    
    if not backup_dir.exists():
        return {"exists": False}
    
    backups = list(backup_dir.glob("windrose-save-*.zip"))
    
    if not backups:
        return {"exists": False}
    
    # 按修改时间排序，取最新的
    latest = max(backups, key=lambda f: f.stat().st_mtime)
    
    stat = latest.stat()
    return {
        "exists": True,
        "filename": latest.name,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "path": str(latest)
    }

def load_state():
    """加载监控状态"""
    state_file = Path(__file__).parent / "state.json"
    
    if state_file.exists():
        try:
            with open(state_file) as f:
                return json.load(f)
        except:
            pass
    
    return {"last_players": 0, "last_check": None}

def save_state(state):
    """保存监控状态"""
    state_file = Path(__file__).parent / "state.json"
    state["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)

# ==================== API 端点 ====================

@app.route('/status')
def status():
    """获取服务器完整状态"""
    proc = get_process_status()
    players = get_player_count()
    backup = get_last_backup()
    state = load_state()
    
    return jsonify({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "process": proc,
        "players": players["count"],
        "last_backup": backup,
        "last_players": state.get("last_players", 0),
        "uptime": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if proc["running"] else None
    })

@app.route('/process')
def process():
    """仅获取进程状态"""
    return jsonify(get_process_status())

@app.route('/players')
def players():
    """仅获取玩家数量"""
    return jsonify(get_player_count())

@app.route('/backup')
def backup_info():
    """获取最新备份信息"""
    return jsonify(get_last_backup())

@app.route('/backup/trigger', methods=['POST'])
def trigger_backup():
    """触发备份（由 Mac 端调用）"""
    from backup import do_backup
    
    reason = request.json.get("reason", "manual")
    result = do_backup(reason)
    
    return jsonify(result)

@app.route('/health')
def health():
    """健康检查"""
    return jsonify({"status": "ok", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

@app.route('/state/update', methods=['POST'])
def update_state():
    """更新状态（由 Mac 端调用）"""
    state = load_state()
    
    if request.json.get("players"):
        state["last_players"] = request.json["players"]
    
    save_state(state)
    return jsonify({"status": "ok", "state": state})

if __name__ == '__main__':
    port = config["server"]["port"]
    host = config["server"]["host"]
    
    print(f"Starting Windrose Status API on {host}:{port}")
    app.run(host=host, port=port, threaded=True)