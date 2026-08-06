"""Project 管理模块。

对应《02_详细设计说明书_SDD.md》第 3.0 节：
- 每个项目拥有独立数据目录（.cliplens/）。
- 图片文件保持原位，仅被索引。
- 删除项目只删 .cliplens/，不触碰原图。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .metadata_db import MetadataDB
from .models import ProjectInfo
from .thumbnail_store import ThumbnailStore
from .vector_store import VectorStore, create_vector_store


def default_app_dir() -> Path:
    """全局数据目录。可用环境变量 CLIPLENS_HOME 覆盖。"""
    import os

    home = os.environ.get("CLIPLENS_HOME")
    if home:
        return Path(home)
    return Path.home() / ".cliplens"


class ProjectHandle:
    """已打开项目的访问句柄。"""

    def __init__(
        self,
        info: ProjectInfo,
        metadata_db: MetadataDB,
        vector_store: VectorStore,
        thumbnail_store: ThumbnailStore,
    ):
        self.info = info
        self.metadata_db = metadata_db
        self.vector_store = vector_store
        self.thumbnail_store = thumbnail_store

    @property
    def data_dir(self) -> Path:
        return self.info.data_dir

    def close(self) -> None:
        self.metadata_db.close()


class ProjectManager:
    """项目管理器，管理项目生命周期。"""

    CLIPLENS_DIRNAME = ".cliplens"

    def __init__(self, app_db_path: Path | None = None):
        self.app_db_path = Path(app_db_path) if app_db_path else (
            default_app_dir() / "app.db"
        )
        self.app_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_app_db()
        self._current: ProjectHandle | None = None

    def _init_app_db(self) -> None:
        conn = sqlite3.connect(str(self.app_db_path))
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL UNIQUE,
                data_dir TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_opened_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS system_config (
                key VARCHAR(50) PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO system_config(key, value) VALUES('app_schema_version', '1')"
        )
        conn.commit()
        conn.close()

    # ---------- 生命周期 ----------
    def create_project(self, name: str, data_dir: Path) -> ProjectHandle:
        data_dir = Path(data_dir).expanduser().resolve()
        cliplens_dir = data_dir / self.CLIPLENS_DIRNAME
        cliplens_dir.mkdir(parents=True, exist_ok=True)

        # project.json
        (cliplens_dir / "project.json").write_text(
            json.dumps(
                {"name": name, "created_at": datetime.now().isoformat()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        conn = sqlite3.connect(str(self.app_db_path))
        cur = conn.execute(
            "INSERT INTO projects(name, data_dir, created_at) VALUES(?, ?, ?)",
            (name, str(data_dir), datetime.now().isoformat()),
        )
        project_id = cur.lastrowid
        conn.commit()
        conn.close()

        info = ProjectInfo(id=project_id, name=name, data_dir=data_dir)
        return self._mount(info)

    def open_project(self, project_id: int) -> ProjectHandle:
        conn = sqlite3.connect(str(self.app_db_path))
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            conn.close()
            raise ValueError(f"项目不存在: {project_id}")
        info = ProjectInfo(
            id=row[0], name=row[1], data_dir=Path(row[2]),
            created_at=row[3], last_opened_at=row[4],
        )
        conn.execute(
            "UPDATE projects SET last_opened_at = ? WHERE id = ?",
            (datetime.now().isoformat(), project_id),
        )
        conn.commit()
        conn.close()
        return self._mount(info)

    def list_projects(self) -> list[ProjectInfo]:
        conn = sqlite3.connect(str(self.app_db_path))
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY last_opened_at DESC"
        ).fetchall()
        conn.close()
        return [
            ProjectInfo(id=r[0], name=r[1], data_dir=Path(r[2]),
                        created_at=r[3], last_opened_at=r[4])
            for r in rows
        ]

    def delete_project(self, project_id: int, purge: bool = False) -> None:
        """删除项目。

        purge=False 时仅从注册表移除并删除数据目录；原图不受影响。
        注：为避免误删，仅删除 .cliplens/ 数据目录，绝不删除任何图片文件。
        """
        if self._current and self._current.info.id == project_id:
            self._current.close()
            self._current = None
        conn = sqlite3.connect(str(self.app_db_path))
        row = conn.execute(
            "SELECT data_dir FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
        conn.close()
        if row:
            cliplens_dir = Path(row[0]) / self.CLIPLENS_DIRNAME
            if cliplens_dir.exists():
                import shutil

                shutil.rmtree(cliplens_dir, ignore_errors=True)

    def current(self) -> ProjectHandle | None:
        return self._current

    # ---------- 内部 ----------
    def _mount(self, info: ProjectInfo) -> ProjectHandle:
        cliplens_dir = info.data_dir / self.CLIPLENS_DIRNAME
        metadata_db = MetadataDB(cliplens_dir / "metadata.db").open()
        vector_store = create_vector_store(cliplens_dir / "vectors.lancedb")
        thumbnail_store = ThumbnailStore(cliplens_dir / "thumbs")
        handle = ProjectHandle(
            info, metadata_db, vector_store, thumbnail_store
        )
        self._current = handle
        return handle
