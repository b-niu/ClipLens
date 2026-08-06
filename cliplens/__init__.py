"""ClipLens - 本地 AI 智能图片浏览与管理工具。

以 Project（项目）为核心组织单元：每个项目拥有独立的数据目录
（.cliplens/），包含 SQLite 元数据库、LanceDB 向量库与缩略图缓存，
图片文件本身保持原始路径不变。
"""

__version__ = "0.1.0"

from .models import (
    ImageStatus,
    ProjectInfo,
    ScanResult,
    SearchQuery,
    SearchResultItem,
    ThumbSize,
)
from .project_manager import ProjectHandle, ProjectManager

__all__ = [
    "ImageStatus",
    "ProjectInfo",
    "ScanResult",
    "SearchQuery",
    "SearchResultItem",
    "ThumbSize",
    "ProjectHandle",
    "ProjectManager",
]
