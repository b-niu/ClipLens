# ClipLens

本地 AI 智能图片浏览与管理工具。

以 **Project（项目）** 为核心组织单元，基于 Python + PySide6 开发，集成 Chinese-CLIP 多模态模型与 LanceDB / SQLite，实现基于自然语言文本的本地图片跨模态检索、流式网格浏览、批量打分、智能筛选与安全的本地文件删除管理。

## 核心特性

- **完全本地化**：模型推理、向量计算、数据存储均在本地，无网络上传
- **Project 管理**：每个项目独立数据目录（`.cliplens/`），图片文件保持原路径不变
- **语义检索**：用自然语言搜索本地图片
- **虚拟化网格**：海量图片流畅浏览（10 万张 < 100ms 检索，60 FPS）
- **安全删除**：软删除 + 系统回收站，防误删

## 项目结构

```
ClipLens/
├── docs/                  # 设计文档
│   ├── 01_需求规格说明书_SRS.md
│   ├── 02_详细设计说明书_SDD.md
│   ├── 03_数据库设计说明书_DB_Design.md
│   ├── 04_软件架构设计文档_SAD.md
│   ├── 05_UI_UX界面设计文档.md
│   ├── 06_API接口设计文档.md
│   ├── 07_测试计划与测试用例.md
│   ├── 08_部署与发布说明.md
│   └── 09_用户使用手册.md
├── cliplens/              # Python 源码
│   ├── models.py          # 数据模型
│   ├── project_manager.py # Project 管理
│   ├── metadata_db.py     # SQLite 封装
│   ├── vector_store.py    # 向量库封装
│   ├── thumbnail_store.py # 缩略图缓存
│   ├── scanner.py         # 扫描建库
│   ├── search.py          # 语义检索
│   ├── trash.py           # 回收站
│   └── cli.py             # CLI 入口
├── requirements.txt       # 依赖
└── ClipLens_Software_Design_Spec.md  # 详细设计说明书（简版）
```

## 快速开始

```bash
pip install -r requirements.txt

# CLI 原型（无需 GUI）
python -m cliplens.cli new demo --dir ./my_project
python -m cliplens.cli scan --project 1 --root ./my_images
python -m cliplens.cli search --project 1 "风景 海边"
```

> 注意：`cli.py` 核心逻辑仅依赖标准库（SQLite）。缩略图生成依赖 Pillow，向量库默认使用内存实现，生产环境替换为 LanceDB + Chinese-CLIP。

## 文档索引

详细的设计说明书、数据库设计、架构文档、API 接口、测试计划、部署说明与用户手册均位于 `docs/` 目录，请按编号阅读。
