#!/usr/bin/env python3
"""
照片筛选工具 — 读 Lightroom 目录星级评分，智能归类，生成作品集候选清单

用法:
  python3 photo_screener.py                    # 汇总报告
  python3 photo_screener.py --stars 4,5        # 只看4-5星
  python3 photo_screener.py --category sunset   # 只看日落类
  python3 photo_screener.py --export candidates # 导出候选图片到 candidates/ 目录
"""
import sqlite3
import os
import sys
import shutil
import tempfile
import json
from pathlib import Path
from collections import defaultdict

# === Config ===
LRCAT = "/Users/liuwendi/Pictures/Lightroom/Lightroom Catalog.lrcat"
PORTFOLIO_DIR = Path("/Users/liuwendi/lio-photo-portfolio")
CANDIDATES_DIR = PORTFOLIO_DIR / "candidates"

# Folder name → category mapping
CATEGORY_RULES = [
    ("日出", "sunrise"), ("sunrise", "sunrise"),
    ("日落", "sunset"), ("sunset", "sunset"), ("晚", "sunset"),
    ("荷花", "lotus"), ("lotus", "lotus"), ("洪湖", "lotus"),
    ("婚礼", "event"), ("wedding", "event"), ("嫁娶", "event"),
    ("深圳湾", "cityscape"), ("蛇口", "cityscape"),
    ("长城", "landscape"), ("北京", "travel"), ("香港", "travel"),
    ("自驾", "travel"), ("徒步", "travel"),
    ("毕业", "event"), ("太极", "event"),
    ("车", "automotive"), ("提车", "automotive"),
    ("星空", "star"), ("星轨", "star"), ("star", "star"),
    ("鸟", "bird"), ("bird", "bird"),
    ("花", "flower"), ("flower", "flower"),
    ("宠物", "pet"), ("狗", "pet"), ("bobby", "pet"),
    ("澳门", "travel"), ("日常", "daily"),
    ("手机", "phone"), ("phone", "phone"),
]

RATING_EMOJI = {1: "⭐", 2: "⭐⭐", 3: "🌟🌟🌟", 4: "🔥🔥🔥🔥", 5: "👑👑👑👑👑"}


def detect_category(path_from_root: str, base_name: str) -> str:
    """Detect category from folder path and filename."""
    combined = (path_from_root + "/" + base_name).lower()
    for keyword, category in CATEGORY_RULES:
        if keyword.lower() in combined:
            return category
    return "other"


def build_absolute_path(root_abs: str, folder_path: str, file_base: str, extension: str) -> str:
    """Construct absolute path from Lightroom catalog data."""
    parts = [root_abs]
    if folder_path and folder_path != ".":
        parts.append(folder_path)
    filename = f"{file_base}.{extension}"
    parts.append(filename)
    return os.path.normpath(os.path.join(*parts))


def check_accessible(filepath: str) -> bool:
    return os.path.exists(filepath)


def format_size(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.1f}MB"
    return f"{size_bytes/1024:.0f}KB"


def load_catalog(stars_filter=None, category_filter=None, accessible_only=False):
    """Query Lightroom catalog and return structured photo data."""
    if not os.path.exists(LRCAT):
        print("❌ Lightroom 目录文件未找到:", LRCAT)
        return []

    # Need a copy because original might be locked by Lightroom
    tmp = tempfile.NamedTemporaryFile(suffix=".lrcat", delete=False)
    tmp.close()
    shutil.copy2(LRCAT, tmp.name)
    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row

    # Build the query
    query = """
    SELECT
        i.rating,
        i.captureTime,
        i.fileFormat,
        f.baseName,
        f.extension,
        f.idx_filename,
        f.originalFilename,
        fo.pathFromRoot,
        r.absolutePath as rootPath,
        (CASE WHEN i.pick = 1 THEN 1 ELSE 0 END) as flagged
    FROM Adobe_images i
    JOIN AgLibraryFile f ON i.rootFile = f.id_local
    JOIN AgLibraryFolder fo ON f.folder = fo.id_local
    JOIN AgLibraryRootFolder r ON fo.rootFolder = r.id_local
    WHERE i.rating IS NOT NULL AND i.rating > 0
    """

    params = []
    if stars_filter:
        placeholders = ",".join("?" * len(stars_filter))
        query += f" AND i.rating IN ({placeholders})"
        params.extend(stars_filter)

    query += " ORDER BY i.rating DESC, i.captureTime DESC"

    cursor = conn.execute(query, params)
    results = []
    for row in cursor:
        rating = int(row["rating"]) if row["rating"] else 0
        path_from_root = row["pathFromRoot"] or ""
        base_name = row["baseName"] or ""
        extension = row["extension"] or "jpg"
        root_path = (row["rootPath"] or "").rstrip("/")

        abs_path = build_absolute_path(root_path, path_from_root, base_name, extension)
        category = detect_category(path_from_root, base_name)
        accessible = check_accessible(abs_path)
        file_size = os.path.getsize(abs_path) if accessible else 0

        if category_filter and category != category_filter:
            continue
        if accessible_only and not accessible:
            continue

        results.append({
            "rating": rating,
            "category": category,
            "path": abs_path,
            "accessible": accessible,
            "size": file_size,
            "size_str": format_size(file_size),
            "root_name": os.path.basename(root_path) if root_path else "?",
            "folder": path_from_root,
            "filename": f"{base_name}.{extension}",
            "capture_time": row["captureTime"],
            "flagged": bool(row["flagged"]),
            "format": row["fileFormat"],
        })

    conn.close()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
    return results


def print_report(photos):
    """Print a beautiful summary report."""
    if not photos:
        print("没有找到符合条件的照片。")
        return

    # Stats
    by_rating = defaultdict(list)
    by_category = defaultdict(list)
    by_volume = defaultdict(list)
    accessible_count = 0
    offline_count = 0
    flagged_count = 0

    for p in photos:
        by_rating[p["rating"]].append(p)
        by_category[p["category"]].append(p)
        by_volume[p["root_name"]].append(p)
        if p["accessible"]:
            accessible_count += 1
        else:
            offline_count += 1
        if p["flagged"]:
            flagged_count += 1

    print("=" * 70)
    print("📷  Lio 照片库 — Lightroom 星级筛选报告")
    print("=" * 70)
    print(f"  总评分照片: {len(photos)} 张")
    print(f"  可访问: {accessible_count} 张  |  离线(外接硬盘): {offline_count} 张")
    if flagged_count:
        print(f"  已标记(旗标): {flagged_count} 张")

    print(f"\n{'—' * 50}")
    print("⭐ 按星级分布:")
    for rating in sorted(by_rating.keys(), reverse=True):
        count = len(by_rating[rating])
        bar = "█" * min(count, 50)
        print(f"  {RATING_EMOJI.get(rating, f'{rating}星'):12s} {count:4d} 张  {bar}")

    print(f"\n{'—' * 50}")
    print("📂 按类别分布:")
    cat_names = {
        "sunrise": "日出", "sunset": "日落", "lotus": "荷花",
        "event": "活动/婚礼", "cityscape": "城市风光", "landscape": "自然风光",
        "travel": "旅行", "automotive": "汽车", "star": "星空/星轨",
        "bird": "鸟类", "flower": "花卉", "pet": "宠物",
        "daily": "日常", "phone": "手机随拍", "other": "其他"
    }
    for cat in sorted(by_category.keys(), key=lambda c: -len(by_category[c])):
        count = len(by_category[cat])
        name = cat_names.get(cat, cat)
        bar = "█" * min(count, 40)
        print(f"  {name:12s} {count:4d} 张  {bar}")

    print(f"\n{'—' * 50}")
    print("💾 按存储位置:")
    for vol in sorted(by_volume.keys(), key=lambda v: -len(by_volume[v])):
        count = len(by_volume[vol])
        accessible = sum(1 for p in by_volume[vol] if p["accessible"])
        status = "✅ 已挂载" if accessible > 0 else "❌ 未连接"
        print(f"  {vol:20s} {count:4d} 张  {status}")

    print(f"\n{'—' * 50}")
    print("🏆 推荐优先级:")
    print("  1️⃣  5星 + 可访问 → 直接可用，数量有限")
    print("  2️⃣  4星 + 可访问 → 精选水平，值得一看")
    print("  3️⃣  3星 + 可访问 → 还不错，看看有没有意外惊喜")
    print("  4️⃣  1-2星 + 可访问 → 曾经标记过但不算好，大概率淘汰")
    print("  5️⃣  高分但离线 → 需要接上对应硬盘才能看到")

    # Show top candidates
    print(f"\n{'—' * 50}")
    print("🔥 高分 + 可访问的候选作品 (5星 & 4星):")
    top = [p for p in photos if p["accessible"] and p["rating"] >= 4]
    top.sort(key=lambda p: (-p["rating"], -p["size"]))

    if top:
        for i, p in enumerate(top[:30], 1):
            flag = "🚩" if p["flagged"] else "  "
            cat_name = cat_names.get(p["category"], p["category"])
            print(f"  {i:2d}. {flag} {RATING_EMOJI.get(p['rating'], '')} [{cat_name:8s}] {p['filename']:40s} {p['size_str']:>8s}")
        if len(top) > 30:
            print(f"  ... 还有 {len(top) - 30} 张")
    else:
        print("  ⚠️ 没有可访问的4-5星照片。请连接外接硬盘后重试。")

    print(f"\n{'=' * 70}")
    print(f"💡 提示:")
    print(f"   python3 photo_screener.py --stars 4,5 --accessible   只看4-5星且可访问")
    print(f"   python3 photo_screener.py --category sunset            只看日落类")
    print(f"   python3 photo_screener.py --export candidates          导出候选到candidates/")
    print(f"   python3 photo_screener.py --list-folders               列出所有照片文件夹")
    print("=" * 70)


def export_candidates(photos):
    """Export candidate photos to candidates/ directory for review."""
    CANDIDATES_DIR.mkdir(exist_ok=True)

    # Filter: 3+ stars and accessible
    candidates = [p for p in photos if p["accessible"] and p["rating"] >= 3]
    candidates.sort(key=lambda p: (-p["rating"], p["category"], p["filename"]))

    if not candidates:
        print("❌ 没有可导出的候选照片 (需要3星以上且可访问)")
        return

    # Export with category prefix and rating tag
    exported = 0
    for p in candidates:
        # Create category subdir
        cat_dir = CANDIDATES_DIR / p["category"]
        cat_dir.mkdir(exist_ok=True)

        # Dest file with rating included
        rating_tag = f"{p['rating']}star"
        src = Path(p["path"])
        dest = cat_dir / f"[{rating_tag}]_{src.name}"

        if not dest.exists():
            try:
                shutil.copy2(src, dest)
                exported += 1
                print(f"  ✅ [{p['rating']}⭐] {p['category']}/{p['filename']:40s} → {dest.name}")
            except Exception as e:
                print(f"  ❌ {p['filename']}: {e}")
        else:
            print(f"  ⏭  已存在: {dest.name}")

    print(f"\n✅ 导出完成: {exported} 张候选图片 → {CANDIDATES_DIR}/")
    print(f"   按类别分目录存放，文件名包含星级标签")


def list_folders():
    """List all photo folders in the catalog grouped by root volume."""
    tmp = tempfile.NamedTemporaryFile(suffix=".lrcat", delete=False)
    tmp.close()
    shutil.copy2(LRCAT, tmp.name)
    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row

    query = """
    SELECT r.absolutePath as root, fo.pathFromRoot, COUNT(i.id_local) as photo_count
    FROM AgLibraryFolder fo
    JOIN AgLibraryRootFolder r ON fo.rootFolder = r.id_local
    LEFT JOIN AgLibraryFile f ON f.folder = fo.id_local
    LEFT JOIN Adobe_images i ON i.rootFile = f.id_local
    GROUP BY fo.id_local
    HAVING photo_count > 0
    ORDER BY r.absolutePath, fo.pathFromRoot
    """
    by_root = defaultdict(list)
    for row in conn.execute(query):
        root = row["root"] or "?"
        path = row["pathFromRoot"] or "."
        count = row["photo_count"]
        full = os.path.join(root, path) if path != "." else root
        exists = os.path.exists(full)
        by_root[root].append((path, count, exists))

    conn.close()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass

    for root, folders in sorted(by_root.items()):
        total = sum(c for _, c, _ in folders)
        root_exists = os.path.exists(root)
        status = "✅" if root_exists else "❌ 离线"
        print(f"\n{status} {root} ({total} photos)")
        for path, count, exists in sorted(folders):
            icon = "📁" if exists else "📁❌"
            print(f"    {icon} {path or '.'}  — {count} 张")


def main():
    stars_filter = None
    category_filter = None
    accessible_only = False
    export_mode = None

    # Parse args
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--stars":
            stars_filter = [int(s.strip()) for s in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--category":
            category_filter = args[i + 1]
            i += 2
        elif args[i] == "--accessible":
            accessible_only = True
            i += 1
        elif args[i] == "--export":
            export_mode = args[i + 1]
            i += 2
        elif args[i] == "--list-folders":
            list_folders()
            return
        else:
            i += 1

    print("🔄 读取 Lightroom 目录...")
    photos = load_catalog(stars_filter, category_filter, accessible_only)

    if export_mode:
        export_candidates(photos)
    else:
        print_report(photos)


if __name__ == "__main__":
    main()
