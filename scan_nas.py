#!/usr/bin/env python3
"""
直接扫描 NAS 成片 + 交叉匹配 Lightroom 评分

NAS 结构: /Volumes/home/Photos/A图片/{year}/{event}/jpg/*.JPG
Lightroom: 通过 baseName 匹配评分

用法:
  python3 scan_nas.py                    # 汇总报告
  python3 scan_nas.py --stars 4,5        # 只看4-5星
  python3 scan_nas.py --category sunset  # 只看日落
  python3 scan_nas.py --export           # 导出候选到 candidates/
"""
import os
import sys
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from collections import defaultdict

LRCAT = "/Users/liuwendi/Pictures/Lightroom/Lightroom Catalog.lrcat"
NAS_BASE = "/Volumes/home/Photos/A图片"
CANDIDATES_DIR = Path("/Users/liuwendi/lio-photo-portfolio/candidates")

CATEGORY_RULES = [
    ("日出", "sunrise"), ("sunset", "sunset"), ("日落", "sunset"), ("晚", "sunset"),
    ("荷花", "lotus"), ("lotus", "lotus"), ("洪湖", "lotus"),
    ("婚礼", "event"), ("wedding", "event"),
    ("深圳湾", "cityscape"), ("蛇口", "cityscape"), ("天文台", "landscape"),
    ("长城", "landscape"), ("北京", "travel"), ("香港", "travel"),
    ("自驾", "travel"), ("徒步", "travel"), ("四川", "travel"), ("上海", "travel"),
    ("毕业", "event"), ("太极", "event"),
    ("车", "automotive"), ("提车", "automotive"), ("领克", "automotive"), ("miat", "automotive"), ("米亚", "automotive"),
    ("星空", "star"), ("星轨", "star"),
    ("鸟", "bird"), ("bird", "bird"),
    ("花", "flower"), ("flower", "flower"), ("樱", "flower"),
    ("宠物", "pet"), ("狗", "pet"), ("波比", "pet"), ("bobby", "pet"),
    ("澳门", "travel"), ("日常", "daily"),
    ("手机", "phone"), ("phonephoto", "phone"),
    ("吉他", "portrait"), ("写真", "portrait"), ("毕业照", "portrait"),
]

RATING_EMOJI = {1: "⭐", 2: "⭐⭐", 3: "🌟🌟🌟", 4: "🔥🔥🔥🔥", 5: "👑👑👑👑👑"}
CAT_NAMES = {
    "sunrise": "日出", "sunset": "日落", "lotus": "荷花",
    "event": "活动/婚礼", "cityscape": "城市风光", "landscape": "自然风光",
    "travel": "旅行", "automotive": "汽车", "star": "星空/星轨",
    "bird": "鸟类", "flower": "花卉", "pet": "宠物",
    "daily": "日常", "phone": "手机随拍", "portrait": "人像/写真",
    "other": "其他"
}


def detect_category(folder_path: str) -> str:
    for keyword, cat in CATEGORY_RULES:
        if keyword.lower() in folder_path.lower():
            return cat
    return "other"


def load_lr_ratings():
    """Extract (baseName, rating) from Lightroom catalog for all rated photos."""
    if not os.path.exists(LRCAT):
        print("⚠️ Lightroom 目录未找到，跳过评分匹配")
        return {}

    tmp = tempfile.NamedTemporaryFile(suffix=".lrcat", delete=False)
    tmp.close()
    try:
        shutil.copy2(LRCAT, tmp.name)
        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
        SELECT f.baseName, i.rating, i.pick, i.captureTime
        FROM Adobe_images i
        JOIN AgLibraryFile f ON i.rootFile = f.id_local
        WHERE i.rating IS NOT NULL AND i.rating > 0
        """)
        ratings = {}
        for row in cursor:
            base = row["baseName"]
            if base and base not in ratings:  # first match wins (usually the primary copy)
                ratings[base] = {
                    "rating": int(row["rating"]),
                    "flagged": bool(row["pick"]),
                    "capture_time": row["captureTime"],
                }
        conn.close()
        os.unlink(tmp.name)
        return ratings
    except Exception as e:
        os.unlink(tmp.name)
        print(f"⚠️ 读取LR失败: {e}")
        return {}


def scan_nas_jpgs():
    """Walk NAS for JPG files in jpg/ subdirs (processed finals)."""
    photos = []
    for root, dirs, files in os.walk(NAS_BASE):
        # Skip raw/, skip hidden
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        for f in files:
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                full_path = os.path.join(root, f)
                # Determine relative path from NAS_BASE for category detection
                rel = os.path.relpath(full_path, NAS_BASE)
                rel_dir = os.path.dirname(rel)

                # Category from folder name
                category = detect_category(rel_dir)

                # File info
                stat = os.stat(full_path)
                size_bytes = stat.st_size
                size_mb = size_bytes / (1024 * 1024)

                photos.append({
                    "path": full_path,
                    "filename": f,
                    "category": category,
                    "folder": rel_dir,
                    "size": size_bytes,
                    "size_mb": size_mb,
                    "size_str": f"{size_mb:.1f}MB" if size_mb >= 1 else f"{size_bytes/1024:.0f}KB",
                })

    return photos


def main():
    stars_filter = None
    category_filter = None
    export_mode = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--stars":
            stars_filter = [int(s.strip()) for s in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--category":
            category_filter = args[i + 1]
            i += 2
        elif args[i] == "--export":
            export_mode = True
            i += 1
        else:
            i += 1

    print("🔄 扫描 NAS: /Volumes/home/Photos/A图片/ ...")
    t0 = time.time()
    nas_photos = scan_nas_jpgs()
    elapsed = time.time() - t0
    print(f"   找到 {len(nas_photos)} 张图片 ({elapsed:.1f}s)")

    print("🔄 加载 Lightroom 评分数据...")
    t0 = time.time()
    lr_ratings = load_lr_ratings()
    elapsed = time.time() - t0
    print(f"   {len(lr_ratings)} 条评分记录 ({elapsed:.1f}s)")

    # Cross-reference
    rated = 0
    unrated = 0
    for p in nas_photos:
        base = os.path.splitext(p["filename"])[0]
        # Try match: exact name, or strip suffixes like -1, -2
        if base in lr_ratings:
            lr = lr_ratings[base]
            p["rating"] = lr["rating"]
            p["flagged"] = lr["flagged"]
            p["has_rating"] = True
            rated += 1
        else:
            # Try stripping trailing -数字
            import re
            clean = re.sub(r'-\d+$', '', base)
            if clean != base and clean in lr_ratings:
                lr = lr_ratings[clean]
                p["rating"] = lr["rating"]
                p["flagged"] = lr["flagged"]
                p["has_rating"] = True
                rated += 1
            else:
                p["rating"] = 0
                p["flagged"] = False
                p["has_rating"] = False
                unrated += 1

    # Filter
    if stars_filter:
        nas_photos = [p for p in nas_photos if p["rating"] in stars_filter]
    if category_filter:
        nas_photos = [p for p in nas_photos if p["category"] == category_filter]

    print(f"\n   ✅ 已匹配评分: {rated} 张")
    print(f"   ⬜ 无评分记录: {unrated} 张")
    print(f"   📊 筛选后: {len(nas_photos)} 张")

    # Report
    print_report(nas_photos)

    if export_mode:
        export_candidates(nas_photos)


def print_report(photos):
    if not photos:
        print("\n没有找到符合条件的照片。")
        return

    by_rating = defaultdict(list)
    by_category = defaultdict(list)
    has_rated = sum(1 for p in photos if p["has_rating"])

    for p in photos:
        by_rating[p["rating"]].append(p)
        by_category[p["category"]].append(p)

    print("\n" + "=" * 70)
    print(f"📷  NAS 成片扫描 — {len(photos)} 张")
    print("=" * 70)
    print(f"  已匹配LR评分: {has_rated} 张  |  未评分: {len(photos) - has_rated} 张")

    print(f"\n{'—' * 50}")
    print("⭐ 按评分分布:")
    for rating in sorted(by_rating.keys(), reverse=True):
        count = len(by_rating[rating])
        if count == 0:
            continue
        emoji = RATING_EMOJI.get(rating, "⬜ 未评分")
        bar = "█" * min(count, 50)
        print(f"  {emoji:16s} {count:4d} 张  {bar}")

    print(f"\n{'—' * 50}")
    print("📂 按类别分布:")
    for cat in sorted(by_category.keys(), key=lambda c: -len(by_category[c])):
        count = len(by_category[cat])
        name = CAT_NAMES.get(cat, cat)
        bar = "█" * min(count, 40)
        print(f"  {name:12s} {count:4d} 张  {bar}")

    # Top picks
    print(f"\n{'—' * 50}")
    print("🔥 高分候选:")
    top = sorted(photos, key=lambda p: (-p["rating"], -p["size"]))
    top = [p for p in top if p["rating"] >= 3][:40]

    if top:
        for i, p in enumerate(top, 1):
            flag = "🚩" if p.get("flagged") else "  "
            cat_name = CAT_NAMES.get(p["category"], p["category"])
            rating_display = RATING_EMOJI.get(p["rating"], f'{p["rating"]}⭐')
            print(f"  {i:2d}. {flag} {rating_display} [{cat_name:12s}] {p['filename']:40s} {p['size_str']:>8s}")
    else:
        print("  (无3星以上照片)")

    # Unrated but large (might be quality)
    unrated_large = sorted(
        [p for p in photos if not p["has_rating"] and p["size_mb"] > 3],
        key=lambda p: -p["size"]
    )[:10]
    if unrated_large:
        print(f"\n{'—' * 50}")
        print("📸 未评分但文件较大(可能高质量):")
        for i, p in enumerate(unrated_large, 1):
            cat_name = CAT_NAMES.get(p["category"], p["category"])
            print(f"  {i:2d}. ⬜ 未评分 [{cat_name:12s}] {p['filename']:40s} {p['size_str']:>8s}")

    print(f"\n{'=' * 70}")
    print("💡 提示:")
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
        name = CAT_NAMES.get(cat, cat)
        print(f"   python3 scan_nas.py --stars 4,5 --category {cat:12s}  # {name}")
    print("   python3 scan_nas.py --export                            # 导出候选")
    print("=" * 70)


def export_candidates(photos):
    candidates = [p for p in photos if p.get("rating", 0) >= 3]
    if not candidates:
        candidates = sorted(photos, key=lambda p: -p["size"])[:30]
        print("⚠️ 无3星以上照片，导出最大的30张作为参考")

    CANDIDATES_DIR.mkdir(exist_ok=True)

    candidates.sort(key=lambda p: (-p.get("rating", 0), p["category"], p["filename"]))

    exported = 0
    for p in candidates:
        cat_dir = CANDIDATES_DIR / p["category"]
        cat_dir.mkdir(exist_ok=True)
        rating = p.get("rating", 0)
        tag = f"{rating}star" if rating > 0 else "norating"
        dest = cat_dir / f"[{tag}]_{p['filename']}"
        if not dest.exists():
            shutil.copy2(p["path"], dest)
            exported += 1
            print(f"  ✅ [{rating}⭐] {p['category']}/{p['filename']}")

    print(f"\n✅ 导出 {exported} 张 → {CANDIDATES_DIR}/")


if __name__ == "__main__":
    main()
