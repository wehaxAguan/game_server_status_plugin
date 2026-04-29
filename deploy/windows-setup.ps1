# Windrose Status API 部署脚本
# 在 Windows Server 上运行

# 检查 Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python 未安装，请先安装 Python 3.x"
    exit 1
}

# 创建目录
$workDir = "C:\windrose-status-api"
if (-not (Test-Path $workDir)) {
    New-Item -ItemType Directory -Path $workDir -Force
}

# 复制文件 (假设已从 GitHub 克隆)
# 如果是从 Mac 上传，需要先 scp 到服务器

# 安装依赖
Write-Host "安装 Python 依赖..."
pip install -r "$workDir\server\requirements.txt"

# 创建 Windows 服务 (使用 NSSM 或直接用定时任务)
# 方案 1: 使用 NSSM (推荐)
$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if ($nssm) {
    nssm install WindroseStatusApi python "$workDir\server\api.py"
    nssm set WindroseStatusApi AppDirectory $workDir\server
    nssm set WindroseStatusApi DisplayName "Windrose Status API"
    nssm start WindroseStatusApi
    Write-Host "服务已创建并启动"
} else {
    Write-Host "NSSM 未安装，请手动安装或使用定时任务启动"
    Write-Host "手动启动: python $workDir\server\api.py"
}

# 测试 API
Write-Host "测试 API..."
Start-Sleep -Seconds 3
$response = Invoke-WebRequest -Uri "http://localhost:8080/health" -TimeoutSec 5 -ErrorAction SilentlyContinue
if ($response.StatusCode -eq 200) {
    Write-Host "API 启动成功！"
    Write-Host "状态查询: http://39.107.87.36:8080/status"
} else {
    Write-Host "API 启动失败，请检查日志"
}