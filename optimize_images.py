#!/usr/bin/env python3
"""
Optimize all gallery images: WebP multi-size + thumbnails + regenerate gallery.json

Output structure:
  optimized/
    thumb/    — 400px WebP, quality 75  (gallery grid)
    display/  — 1200px WebP, quality 82 (main display)
    full/     — 2560px WebP, quality 85 (lightbox)

Size targets:
  thumb:   ~15-30KB  each
  display: ~80-150KB each
  full:    ~200-500KB each
"""
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).parent
IMAGES_DIR = ROOT / "images"
OPT_DIR = ROOT / "optimized"

SIZES = {
    "thumb":   400,
    "display": 1200,
    "full":    2560,
}
QUALITY = {"thumb": 75, "display": 82, "full": 85}
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
EXCLUDE = {"best2025.jpg", "best2025-hero.jpg", "avatar.jpg"}

result = []
stats = {"total_original_mb": 0, "total_optimized_mb": 0, "count": 0}


def make_webp(src: Path, dst: Path, max_width: int, quality: int) -> int:
    """Create WebP, resizing to max_width if larger. Returns file size in bytes."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        img = Image.open(src)
        img.load()
    except (OSError, IOError) as e:
        print(f"  ⚠️  Skipping corrupted: {src.relative_to(ROOT)} ({e})")
        return 0

    if img.mode in ("RGBA", "P", "CMYK"):
        img = img.convert("RGB")

    w, h = img.size
    if w > max_width:
        ratio = max_width / w
        new_size = (max_width, int(h * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    img.save(dst, "WEBP", quality=quality, method=6)
    return dst.stat().st_size


def collect_images():
    """Walk images/ and return list of (relative_path, category, original_path)."""
    entries = []
    for item in sorted(IMAGES_DIR.iterdir()):
        if item.is_dir():
            category = item.name
            for img_file in sorted(item.iterdir()):
                if img_file.suffix.lower() not in EXTENSIONS:
                    continue
                if img_file.name in EXCLUDE:
                    continue
                rel = f"{category}/{img_file.name}"
                entries.append((rel, category, img_file))
        elif item.suffix.lower() in EXTENSIONS and item.name not in EXCLUDE:
            entries.append((item.name, "uncategorized", item))
    return entries


# --- Main ---
entries = collect_images()
print(f"Found {len(entries)} images to optimize\n")

for rel, category, src in entries:
    stem = Path(rel).stem
    # Flatten directory structure for optimized output
    flat_name = f"{category}__{Path(rel).name}" if category != "uncategorized" else Path(rel).name

    # Strip extension, will add .webp
    base = Path(flat_name).stem

    size_info = {}
    for size_name, max_w in SIZES.items():
        dst = OPT_DIR / size_name / f"{base}.webp"
        bytes_written = make_webp(src, dst, max_w, QUALITY[size_name])
        size_info[size_name] = f"optimized/{size_name}/{base}.webp"
        size_info[f"{size_name}_kb"] = bytes_written // 1024

    orig_kb = src.stat().st_size // 1024
    stats["total_original_mb"] += orig_kb / 1024
    stats["total_optimized_mb"] += (size_info["thumb_kb"] + size_info["display_kb"] + size_info["full_kb"]) / 1024
    stats["count"] += 1

    print(f"  {rel:40s} {orig_kb:5d}KB → thumb:{size_info['thumb_kb']:3d}KB  display:{size_info['display_kb']:4d}KB  full:{size_info['full_kb']:4d}KB")

    result.append({
        "title": stem,
        "category": category,
        "thumb": size_info["thumb"],
        "display": size_info["display"],
        "full": size_info["full"],
        "thumb_kb": size_info["thumb_kb"],
        "display_kb": size_info["display_kb"],
        "full_kb": size_info["full_kb"],
    })

# --- Write gallery.json ---
gallery_path = ROOT / "gallery.json"
with open(gallery_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"✅ {stats['count']} images optimized")
print(f"   原始总大小: {stats['total_original_mb']:.1f} MB")
print(f"   优化后总计: {stats['total_optimized_mb']:.1f} MB (3 sizes)")
print(f"   节省: {stats['total_original_mb'] - stats['total_optimized_mb']:.1f} MB ({(1 - stats['total_optimized_mb']/max(stats['total_original_mb'],0.01))*100:.0f}%)")
print(f"   gallery.json written → {gallery_path}")
