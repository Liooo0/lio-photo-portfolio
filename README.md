# lio-photo-portfolio — 摄影作品集

延时 · 日出 · 星空 · 花鸟。器材：Panasonic S5M2。

> 在线浏览：https://liooo0.github.io/lio-photo-portfolio/ （GitHub Pages）

## 架构

```
原图 → generate_gallery.py / optimize_images.py
     → 三档 WebP（thumb ~400px / display ~1200px / full 2560px）
     → gallery.json 数据驱动 → 原生 JS 画廊（零框架、零构建）
```

## 图片管理（重要）

- **入库**：仅 `optimized/`（三档 WebP，约 7MB）与画廊元数据
- **原图**：不入库。备份在本机 `~/Pictures/lio-photo-raw-backup/`
- **历史**：2026-08 用 `git filter-repo` 清掉 images/ 与 thumbnails/ 的历史，仓库 573MB → ~57MB

新增作品流程：

```bash
# 原图放进 images/（gitignored）→ 跑优化流水线 → 更新 gallery.json
python3 optimize_images.py
python3 generate_gallery.py
```

## 部署

```bash
bash deploy.sh   # 提交并推送，GitHub Pages 自动更新
```

## 版权

代码 MIT。照片版权归作者所有，转载需授权。