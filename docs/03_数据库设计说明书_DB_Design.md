# ClipLens 数据库设计说明书 (Database Design Specification)

| 项目名称 | ClipLens |
|---------|----------|
| 版本 | v1.0 |
| 日期 | 2026-08-06 |

---

## 1. 设计概述

ClipLens 采用**双层数据库架构**：

1. **全局应用库 (app.db)**：存储所有 Project 的注册信息，位于 `~/.cliplens/app.db`。
2. **项目专属库**：每个 Project 拥有独立的 `metadata.db`（SQLite）与 `vectors.lancedb`（向量库），位于该项目的数据目录 `.cliplens/` 下。

> 设计原则：**数据按项目隔离**，删除/分享项目只需操作其 `.cliplens/` 目录，图片文件保持原位不受影响。

### 1.1 数据存储位置汇总

| 数据 | 引擎 | 位置 | 归属 |
|------|------|------|------|
| 项目注册表 | SQLite | `~/.cliplens/app.db` | 全局 |
| 图片元数据 | SQLite | `<project>/.cliplens/metadata.db` | 项目 |
| 图像向量 | LanceDB | `<project>/.cliplens/vectors.lancedb` | 项目 |
| 缩略图 | 文件系统 | `<project>/.cliplens/thumbs/` | 项目 |

---

## 2. 全局应用库 (app.db)

### 2.1 projects 表

```sql
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,    -- 项目名称
    data_dir TEXT NOT NULL,               -- 项目数据目录（.cliplens 所在路径）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_opened_at TIMESTAMP              -- 最近打开时间
);
```

**索引**：`name` 唯一约束即可，`last_opened_at` 可加索引用于排序。

---

## 3. 项目元数据库 (metadata.db)

存放于各项目 `<data_dir>/.cliplens/metadata.db`。

### 3.1 images 表（主图片信息）

```sql
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,       -- 文件绝对路径
    file_name TEXT NOT NULL,              -- 文件名
    file_size INTEGER NOT NULL,           -- 文件大小 (Bytes)
    width INTEGER NOT NULL,               -- 图片原始宽度
    height INTEGER NOT NULL,              -- 图片原始高度
    mtime REAL NOT NULL,                  -- 文件修改时间戳
    md5_hash VARCHAR(32) NOT NULL,        -- 文件哈希（用于去重）
    rating INTEGER DEFAULT 0,             -- 评分 (0-5分)
    status VARCHAR(16) DEFAULT 'OK',      -- OK / CORRUPTED / MISSING
    is_deleted TINYINT DEFAULT 0,         -- 软删除标志 (0:正常, 1:回收站)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_images_path ON images(file_path);
CREATE INDEX idx_images_rating ON images(rating);
CREATE INDEX idx_images_deleted ON images(is_deleted);
CREATE INDEX idx_images_md5 ON images(md5_hash);
```

### 3.2 tags 表（标签）

```sql
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(50) UNIQUE NOT NULL
);
```

### 3.3 image_tags 表（图片-标签关联）

```sql
CREATE TABLE IF NOT EXISTS image_tags (
    image_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (image_id, tag_id),
    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX idx_image_tags_tag ON image_tags(tag_id);
```

### 3.4 system_config 表（系统配置）

```sql
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(50) PRIMARY KEY,
    value TEXT NOT NULL
);
```

**典型键值**：`scan_roots`（JSON 数组，扫描来源目录）、`thumbnail_size`、`last_batch_size`。

---

## 4. 向量库 (vectors.lancedb)

LanceDB 表结构，位于各项目 `<data_dir>/.cliplens/vectors.lancedb`。

| 字段 | 类型 | 说明 |
|------|------|------|
| image_id | INT64 | 关联本项目 SQLite `images.id` |
| vector | FixedSizeList[512], Float32 | CLIP 图像 Embedding |
| updated_at | TIMESTAMP | 向量创建/更新时间 |

**检索**：LanceDB 原生 Cosine 距离最近邻查询（Top-N）。

---

## 5. ER 关系图（文本描述）

```
app.db:  projects(1) ──管理──> 每个项目独立数据库

metadata.db:
  images(1) ──<N>── image_tags <N>── (1) tags
  images 关联向量库 vectors.lancedb.image_id
```

---

## 6. 容量估算（单项目 10 万张）

| 数据 | 估算体积 |
|------|---------|
| images 表（含索引） | 约 60~100 MB |
| 向量库（10 万 × 512×4B） | 约 260~300 MB |
| 缩略图（WebP 256px，懒加载） | 约 3~5 GB（可控，设上限 + LRU 淘汰） |

---

## 7. 数据一致性保障

1. **软删除状态**：`is_deleted` 标志与界面同步，物理删除才移除记录。
2. **死链校验**：启动时比对 `file_path` 存在性。
3. **级联删除**：图片物理删除时，级联清理 `image_tags` 与对应向量、缩略图。
4. **事务**：批量操作（评分/删除）使用 SQLite 事务保证原子性。
