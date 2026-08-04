#!/usr/bin/env python3
"""
Scan images/ → generate thumbnails → output gallery.json

Usage:  python3 generate_gallery.py
Thumbnails are written to thumbnails/ (800px wide, JPEG 85% quality).
Only re-generates when source is newer than existing thumbnail.
"""
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).parent
IMAGES_DIR = ROOT / "images"
THUMBS_DIR = ROOT / "thumbnails"
OUTPUT = ROOT / "gallery.json"

THUMB_WIDTH = 800
THUMB_QUALITY = 85
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
EXCLUDE = {"best2025.jpg", "best2025-hero.jpg", "best2025-hero.webp", "avatar.jpg"}

result = []
generated = 0
skipped = 0


def make_thumb(src: Path, dst: Path) -> None:
    """Create thumbnail, preserving aspect ratio. Only overwrites if source is newer."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and src.stat().st_mtime <= dst.stat().st_mtime:
        return  # already up to date

    try:
        img = Image.open(src)
        img.load()
    except (OSError, IOError) as e:
        print(f"  ⚠️  Skipping corrupted: {src.relative_to(ROOT)} ({e})")
        return False

    # Convert RGBA/CMYK to RGB for JPEG
    if img.mode in ("RGBA", "P", "CMYK"):
        img = img.convert("RGB")
    w, h = img.size
    ratio = THUMB_WIDTH / w
    new_size = (THUMB_WIDTH, int(h * ratio))
    img.thumbnail(new_size, Image.LANCZOS)
    img.save(dst, "JPEG", quality=THUMB_QUALITY, optimize=True)
    return True  # newly generated


for item in sorted(IMAGES_DIR.iterdir()):
    if item.is_dir():
        category = item.name
        for img_file in sorted(item.iterdir()):
            if img_file.suffix.lower() not in EXTENSIONS:
                continue
            if img_file.name in EXCLUDE:
                continue
            thumb_dst = THUMBS_DIR / category / img_file.name
            status = make_thumb(img_file, thumb_dst)
            if status is True:
                print(f"  ✨ {category}/{img_file.name}")
                generated += 1
            elif status is None:
                skipped += 1
            else:
                continue  # corrupted, skip entirely
            result.append({
                "title": img_file.stem,
                "category": category,
                "src": f"images/{category}/{img_file.name}",
                "thumb": f"thumbnails/{category}/{img_file.name}"
            })
    elif item.suffix.lower() in EXTENSIONS and item.name not in EXCLUDE:
        thumb_dst = THUMBS_DIR / item.name
        status = make_thumb(item, thumb_dst)
        if status is True:
            print(f"  ✨ {item.name}")
            generated += 1
        elif status is None:
            skipped += 1
        else:
            continue  # corrupted, skip entirely
        result.append({
            "title": item.stem,
            "category": "uncategorized",
            "src": f"images/{item.name}",
            "thumb": f"thumbnails/{item.name}"
        })

# 合并保护：重新生成会丢失手补的 exif/location/geo，先按 title 读旧数据再合并
# （与 tools.py deploy 同一口径；deploy.sh 走的就是本脚本，不能丢数据）
# 注：本脚本按"目录=分类"归类，根目录散图会被归成 uncategorized，且只生成
# thumbnails/ 旧式路径 —— 所以旧条目已有的 category 和 optimized 三级路径一并保留
old_by_title = {}
if OUTPUT.exists():
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            old_by_title = {e.get("title"): e for e in json.load(f) if e.get("title")}
    except Exception:
        pass
for item in result:
    old = old_by_title.get(item["title"]) or {}
    if old.get("exif"):
        item["exif"] = old["exif"]
    item["location"] = old.get("location", "")
    if old.get("geo"):
        item["geo"] = old["geo"]
    if old.get("category"):
        item["category"] = old["category"]
    if old.get("display") and old.get("full"):
        item["thumb"] = old.get("thumb") or item["thumb"]
        item["display"] = old["display"]
        item["full"] = old["full"]
        for kb_key in ("thumb_kb", "display_kb", "full_kb"):
            if old.get(kb_key):
                item[kb_key] = old[kb_key]

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"\nDone: {len(result)} images → {OUTPUT}")
print(f"Thumbnails: {generated} new, {skipped} up-to-date")
