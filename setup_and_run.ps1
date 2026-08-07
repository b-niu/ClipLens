# ==============================================================================
# ClipLens 一键初始化与启动脚本 (PowerShell UTF-8)
# ==============================================================================

$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       ClipLens 本地 AI 智能图片管理系统 - 一键启动器        " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. 检查 uv 工具
Write-Host ""
Write-Host "[1/3] 检查 uv 环境..." -ForegroundColor Yellow
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    Write-Host "[FAIL] 未检测到 uv 命令，请先安装 uv 或将其添加至 PATH！" -ForegroundColor Red
    Read-Host "按回车键退出..."
    exit 1
}
Write-Host "[OK] uv 已就绪" -ForegroundColor Green

# 2. 检查 PyTorch CUDA 状态及 cn-clip 状态
Write-Host ""
Write-Host "[2/3] 检查 PyTorch (CUDA) 状态与依赖..." -ForegroundColor Yellow

$torchCudaCheck = uv run python -c "import torch; print(torch.cuda.is_available())" 2>$null
if ($torchCudaCheck -ne "True") {
    Write-Host "[!] 未检测到可用 CUDA 版 PyTorch，正在从阿里云/清华源安装带有 GPU 支持的 PyTorch..." -ForegroundColor Yellow
    uv pip install torch torchvision -f https://mirrors.aliyun.com/pytorch-wheels/cu124/ -i https://pypi.tuna.tsinghua.edu.cn/simple
}

$cnClipCheck = uv run python -c "import cn_clip" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] 正在补充安装 cn-clip 依赖..." -ForegroundColor Yellow
    uv pip install cn-clip -i https://pypi.tuna.tsinghua.edu.cn/simple
}
Write-Host "[OK] 项目依赖准备就绪" -ForegroundColor Green

# 3. 环境与模型权重初始化检查
Write-Host ""
Write-Host "[3/3] 校验 CUDA GPU 及模型权重..." -ForegroundColor Yellow
uv run python .\init_env.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] 模型初始化失败，请检查上方错误提示。" -ForegroundColor Red
    Read-Host "按回车键退出..."
    exit 1
}

# 4. 启动应用
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       初始化完成！正在启动 ClipLens 系统...              " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

uv run python .\main.py
