"""多模态检索与混合查询模块。

对应《02_详细设计说明书_SDD.md》第 3.2 节：
- 文本 → 向量 → LanceDB 余弦检索（当前项目内）。
- 超采样（oversample=5）+ SQLite 组合过滤 + 批量预取展示字段。
"""
from __future__ import annotations

from pathlib import Path

from .models import SearchQuery, SearchResultItem, ThumbSize
from .project_manager import ProjectHandle


class SearchEngine:
    """在当前激活 Project 内执行检索。"""

    def __init__(self, project: ProjectHandle):
        self.project = project

    def search(self, query: SearchQuery) -> list[SearchResultItem]:
        md = self.project.metadata_db
        vs = self.project.vector_store
        thumbs = self.project.thumbnail_store

        # 1. 文本 → 向量（原型用查询哈希伪向量；生产调用 CLIP Text Encoder）
        query_vector = _query_vector(query.text)

        # 2. 超采样向量检索
        oversampled = vs.search(query_vector, query.top_n * query.oversample)

        # 3. SQLite 组合过滤 + 批量预取展示字段
        candidate_ids = [iid for iid, _ in oversampled]
        display = md.fetch_display_fields(candidate_ids)
        # 一次性批量获取所有候选图片的标签，避免 N+1
        all_tags = md.batch_get_tags(candidate_ids)

        items: list[SearchResultItem] = []
        for iid, score in oversampled:
            rec = display.get(iid)
            if rec is None:
                continue  # 向量存在但元数据缺失 → 启动对账时会清理
            if rec["is_deleted"]:
                continue
            if rec["rating"] < query.min_rating:
                continue
            if not _in_date_range(rec["created_at"], query.date_from, query.date_to):
                continue
            # 标签过滤（全部命中）
            item_tags = all_tags.get(iid, [])
            if query.tags and not set(query.tags).issubset(set(item_tags)):
                continue
            file_path = Path(rec["file_path"])
            items.append(
                SearchResultItem(
                    image_id=iid,
                    score=score,
                    file_path=file_path,
                    file_name=rec["file_name"],
                    rating=rec["rating"],
                    status=rec["status"],
                    is_deleted=bool(rec["is_deleted"]),
                    width=rec["width"],
                    height=rec["height"],
                    tags=item_tags,
                    thumbnail_path=thumbs.abs_path(file_path, ThumbSize.VIEW_256),
                    preview_path=thumbs.abs_path(file_path, ThumbSize.PREVIEW_1024),
                )
            )
            if len(items) >= query.top_n:
                break
        return items


def _in_date_range(
    created_at: object,
    date_from: object,
    date_to: object,
) -> bool:
    """根据 images.created_at（ISO 字符串或 None）做日期范围过滤。"""
    if date_from is None and date_to is None:
        return True
    if not created_at:
        return False  # 无法确定创建时间则不过滤通过（需要范围时）
    ts = str(created_at)[:10]  # YYYY-MM-DD
    if date_from is not None and ts < str(date_from)[:10]:
        return False
    if date_to is not None and ts > str(date_to)[:10]:
        return False
    return True


def _query_vector(text: str) -> list[float]:
    """原型：基于文本哈希生成伪向量；生产替换为 Chinese-CLIP Text Encoder。"""
    import math

    from .scanner import _PseudoRandom

    seed = abs(hash(text)) % (2**32)
    rnd = _PseudoRandom(seed)
    v = [rnd.next() for _ in range(512)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]
