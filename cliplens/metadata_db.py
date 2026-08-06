"""SQLite 元数据封装（metadata.db）。

对应《03_数据库设计说明书_DB_Design.md》第 3 节的表结构。
注意：本模块仅依赖标准库 sqlite3，可在未安装第三方依赖时独立运行，
便于核心逻辑的单元测试与原型验证。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import ImageRecord, ImageStatus

SCHEMA_VERSION = 1

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    mtime REAL NOT NULL,
    md5_hash VARCHAR(32) NOT NULL,
    rating INTEGER DEFAULT 0,
    status VARCHAR(16) DEFAULT 'OK',
    is_deleted TINYINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_images_path ON images(file_path);
CREATE INDEX IF NOT EXISTS idx_images_rating ON images(rating);
CREATE INDEX IF NOT EXISTS idx_images_deleted ON images(is_deleted);
CREATE INDEX IF NOT EXISTS idx_images_md5 ON images(md5_hash);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(50) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS image_tags (
    image_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (image_id, tag_id),
    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_image_tags_tag ON image_tags(tag_id);

CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(50) PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class MetadataDB:
    """项目内 SQLite 元数据库封装。

    说明：按照 SAD 并发设计，所有写操作应经过唯一 DB Writer 线程串行执行。
    本类提供事务上下文管理器以便正确使用。
    """

    def __init__(self, db_path: Path, schema_version: int = SCHEMA_VERSION):
        self.db_path = Path(db_path)
        self.schema_version = schema_version
        self._conn: sqlite3.Connection | None = None

    # ---------- 生命周期 ----------
    def open(self) -> "MetadataDB":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_CREATE_TABLES)
        self.set_config("schema_version", str(self.schema_version))
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self):
        """事务上下文，用于批量写操作保证原子性。"""
        if self._conn is None:
            raise RuntimeError("MetadataDB 未打开")
        try:
            self._conn.execute("BEGIN")
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ---------- 配置 ----------
    def get_config(self, key: str, default: str | None = None) -> str | None:
        cur = self._conn.execute(
            "SELECT value FROM system_config WHERE key = ?", (key,)
        )
        row = cur.fetchone()
        return row["value"] if row else default

    def set_config(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO system_config(key, value) VALUES(?, ?)",
            (key, value),
        )
        self._conn.commit()

    # ---------- images 增删改查 ----------
    def upsert_image(self, rec: ImageRecord) -> int:
        """按 file_path 插入或更新图片记录，返回 image id。"""
        with self.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO images
                    (file_path, file_name, file_size, width, height, mtime,
                     md5_hash, rating, status, is_deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    file_name=excluded.file_name,
                    file_size=excluded.file_size,
                    width=excluded.width,
                    height=excluded.height,
                    mtime=excluded.mtime,
                    md5_hash=excluded.md5_hash,
                    status=excluded.status,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    str(rec.file_path), rec.file_name, rec.file_size,
                    rec.width, rec.height, rec.mtime, rec.md5_hash,
                    rec.rating, rec.status.value, int(rec.is_deleted),
                ),
            )
            image_id = cur.lastrowid or self._get_id_by_path(rec.file_path)
        return image_id

    def get_image(self, image_id: int) -> ImageRecord | None:
        row = self._conn.execute(
            "SELECT * FROM images WHERE id = ?", (image_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def set_rating(self, image_ids: list[int], rating: int) -> None:
        if not image_ids:
            return
        placeholders = ",".join("?" for _ in image_ids)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE images SET rating = ?, updated_at = CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders})",
                [rating, *image_ids],
            )

    def soft_delete(self, image_ids: list[int], deleted: bool = True) -> None:
        if not image_ids:
            return
        placeholders = ",".join("?" for _ in image_ids)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE images SET is_deleted = ?, updated_at = CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders})",
                [int(deleted), *image_ids],
            )

    def purge(self, image_ids: list[int]) -> None:
        """彻底删除记录（级联清理 image_tags）。"""
        if not image_ids:
            return
        placeholders = ",".join("?" for _ in image_ids)
        with self.transaction() as conn:
            conn.execute(
                f"DELETE FROM image_tags WHERE image_id IN ({placeholders})",
                image_ids,
            )
            conn.execute(
                f"DELETE FROM images WHERE id IN ({placeholders})", image_ids
            )

    # ---------- tags ----------
    def add_tag(self, image_id: int, name: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,)
            )
            tag_id = conn.execute(
                "SELECT id FROM tags WHERE name = ?", (name,)
            ).fetchone()["id"]
            conn.execute(
                "INSERT OR IGNORE INTO image_tags(image_id, tag_id) VALUES (?, ?)",
                (image_id, tag_id),
            )

    def remove_tag(self, image_id: int, name: str) -> None:
        with self.transaction() as conn:
            tag_id = conn.execute(
                "SELECT id FROM tags WHERE name = ?", (name,)
            ).fetchone()
            if tag_id:
                conn.execute(
                    "DELETE FROM image_tags WHERE image_id = ? AND tag_id = ?",
                    (image_id, tag_id["id"]),
                )

    def get_tags(self, image_id: int) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN image_tags it ON it.tag_id = t.id
            WHERE it.image_id = ?
            """,
            (image_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    # ---------- 检索辅助 ----------
    def fetch_display_fields(self, image_ids: list[int]) -> dict[int, dict]:
        """批量预取展示字段，避免 N+1 查询（见 API 文档第 3 节）。"""
        if not image_ids:
            return {}
        placeholders = ",".join("?" for _ in image_ids)
        rows = self._conn.execute(
            f"SELECT * FROM images WHERE id IN ({placeholders})", image_ids
        ).fetchall()
        return {r["id"]: dict(r) for r in rows}

    def _get_id_by_path(self, path: Path) -> int:
        row = self._conn.execute(
            "SELECT id FROM images WHERE file_path = ?", (str(path),)
        ).fetchone()
        return row["id"] if row else -1

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ImageRecord:
        return ImageRecord(
            id=row["id"],
            file_path=Path(row["file_path"]),
            file_name=row["file_name"],
            file_size=row["file_size"],
            width=row["width"],
            height=row["height"],
            mtime=row["mtime"],
            md5_hash=row["md5_hash"],
            rating=row["rating"],
            status=ImageStatus(row["status"]),
            is_deleted=bool(row["is_deleted"]),
        )
