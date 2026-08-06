"""ClipLens 数据模型定义。

与《03_数据库设计说明书_DB_Design.md》中的表结构对应。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class ImageStatus(str, Enum):
    """图片状态（对应 images.status 字段）。"""

    OK = "OK"
    CORRUPTED = "CORRUPTED"  # 解码失败，无法提取向量
    MISSING = "MISSING"      # 磁盘文件已失效（死链）


class ThumbSize(Enum):
    """缩略图两种规格（WebP）。"""

    VIEW_256 = (256, 256)          # 网格缩略图
    PREVIEW_1024 = (1024, 1024)    # 预览大图


@dataclass
class ProjectInfo:
    """项目元信息（对应 app.db 的 projects 表）。"""

    id: int
    name: str
    data_dir: Path                # .cliplens 所在路径
    created_at: datetime | None = None
    last_opened_at: datetime | None = None


@dataclass
class ScanResult:
    """增量扫描结果。"""

    new: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)


@dataclass
class ImageRecord:
    """项目内图片记录（对应 metadata.db 的 images 表）。"""

    id: int
    file_path: Path
    file_name: str
    file_size: int
    width: int
    height: int
    mtime: float
    md5_hash: str
    rating: int = 0
    status: ImageStatus = ImageStatus.OK
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class SearchQuery:
    """检索查询参数。"""

    text: str = ""
    min_rating: int = 0
    tags: list[str] = field(default_factory=list)
    date_from: datetime | None = None
    date_to: datetime | None = None
    top_n: int = 100
    oversample: int = 5  # 超采样倍率，向量检索取 top_n × oversample


@dataclass
class SearchResultItem:
    """检索结果项（含 UI 展示所需字段，避免 N+1 查询）。"""

    image_id: int
    score: float
    file_path: Path
    file_name: str = ""
    rating: int = 0
    status: ImageStatus = ImageStatus.OK
    is_deleted: bool = False
    width: int = 0
    height: int = 0
    tags: list[str] = field(default_factory=list)
    thumbnail_path: Path | None = None
    preview_path: Path | None = None
