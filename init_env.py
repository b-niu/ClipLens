"""ClipLens 环境初始化与模型下载脚本。

功能：
1. 自动创建默认的数据与模型存放目录 (~/.cliplens/models)
2. 自动下载推荐的 Chinese-CLIP 权重 (ViT-L/14@336px)
3. 验证当前 GPU / CUDA 环境配置
"""
import os
import sys
from pathlib import Path


RECOMMENDED_MODEL = "ViT-L-14-336"


def get_model_dir() -> Path:
    """获取模型存放绝对路径。"""
    custom_path = os.environ.get("CLIPLENS_MODEL_PATH")
    if custom_path:
        return Path(custom_path)
    return Path.home() / ".cliplens" / "models"


def check_gpu_environment():
    """检查硬件与 PyTorch CUDA 支持（强制要求 CUDA 支持）。"""
    print("=" * 60)
    print(" 1. 检查 PyTorch 及 CUDA 运行环境")
    print("=" * 60)
    try:
        import torch
        print(f"[OK] PyTorch 版本: {torch.__version__}")
        
        if not torch.cuda.is_available():
            print("[FAIL] 错误：当前安装的 PyTorch 是 CPU 版本或未检测到可用 CUDA 显卡驱动！")
            print("       项目强制要求 CUDA 硬件加速。")
            print("       请运行以下指令重新安装 CUDA 版本的 PyTorch:")
            print("       uv pip install torch torchvision -f https://mirrors.aliyun.com/pytorch-wheels/cu124/")
            sys.exit(1)
            
        device_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        print(f"[OK] 检测到 GPU: {device_name}")
        print(f"[OK] 显存容量: {vram_gb:.2f} GB")
    except ImportError:
        print("[FAIL] PyTorch 未安装，请先使用 `uv pip install torch torchvision -f https://mirrors.aliyun.com/pytorch-wheels/cu124/` 安装。")
        sys.exit(1)




def download_model_weights(model_name: str = RECOMMENDED_MODEL):
    """下载 Chinese-CLIP 模型权重。"""
    model_dir = get_model_dir()
    model_dir.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 60)
    print(f" 2. 下载 Chinese-CLIP 权重文件: {model_name}")
    print(f"    存放路径: {model_dir}")
    print("=" * 60)

    try:
        import torch
        import cn_clip.clip as clip
        from cn_clip.clip import load_from_name

        print("正在连接下载源 (ModelScope / HuggingFace)...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # 使用 cn_clip 官方接口自动下载并校验权重
        model, preprocess = load_from_name(
            model_name,
            device=device,
            download_root=str(model_dir),
            use_modelscope=True
        )
        print(f"\n[OK] 模型权重 {model_name} 初始化并加载成功！")

    except ImportError as e:
        print(f"[FAIL] 缺少依赖包: {e}")
        print("    请在命令行运行 `uv sync` 完成环境同步后再试。")
        sys.exit(1)
    except Exception as e:
        print(f"[FAIL] 模型下载/加载失败: {e}")
        print("    请检查网络连接或尝试手动从 ModelScope/HuggingFace 下载。")
        sys.exit(1)


def main():
    print(">>> ClipLens 软件环境与模型初始化工具 <<<\n")
    check_gpu_environment()
    download_model_weights()
    print("\n" + "=" * 60)
    print("[OK] 环境初始化完成！可以直接运行软件进行测试。")
    print("=" * 60)


if __name__ == "__main__":
    main()
