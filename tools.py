#!/usr/bin/env python3
"""
Lio 摄影工具箱

用法:
  python3 tools.py scan        扫描NAS成片+LR评分 → 候选清单
  python3 tools.py deploy      读取LR黄标照片 → 自动提取+优化+更新网站 (dry-run)
  python3 tools.py deploy --go 同上, 实际执行并git push
  python3 tools.py exif        从RAW回填EXIF (dry-run)
  python3 tools.py exif --go   实际执行

暗号:
  在Lightroom里给想上线的照片打 黄色色标(+评分)
  然后跑 python3 tools.py deploy --go 就自动全部上线
  想撤销就在LR里取消黄标, 再跑一次deploy --go
"""

import sys, os, json, shutil, sqlite3, tempfile, subprocess, re
from pathlib import Path
from collections import defaultdict
from PIL import Image

LRCAT = os.path.expanduser("~/Pictures/Lightroom/Lightroom Catalog.lrcat")
NAS = "/Volumes/home/Photos/A图片"
ROOT = Path(__file__).parent
OPT_DIR = ROOT / "optimized"
SIZES = {"thumb": (400, 75), "display": (1200, 82), "full": (2560, 85)}
RAW_EXTS = {".rw2", ".cr2", ".cr3", ".dng", ".nef", ".arw"}

CAT_RULES = [
    ("日出", "sunrise"), ("日落", "sunset"), ("晚霞", "sunset"),
    ("荷花", "lotus"), ("洪湖", "lotus"),
    ("深圳湾", "cityscape"), ("天文台", "landscape"), ("蛇口", "cityscape"),
    ("车", "automotive"), ("领克", "automotive"),
    ("星空", "star"), ("萤火虫", "star"),
    ("鸟", "bird"), ("花", "flower"), ("樱", "flower"), ("猫", "pet"), ("狗", "pet"),
    ("北京", "travel"), ("四川", "travel"), ("南京", "travel"), ("上海", "travel"),
    ("澳门", "travel"), ("香港", "travel"), ("厦门", "travel"), ("阳朔", "travel"),
    ("稻城", "travel"), ("山西", "travel"), ("云南", "travel"), ("贵州", "travel"),
    ("cicf", "event"), ("同人展", "event"), ("漫展", "event"), ("嘉年华", "event"),
    ("瀑布", "landscape"), ("公园", "landscape"), ("山", "landscape"),
    ("婚礼", "event"), ("毕业", "event"), ("领证", "event"),
]
CAT_NAMES = {"sunrise": "日出", "sunset": "日落", "lotus": "荷花", "cityscape": "城市",
             "landscape": "风光", "star": "星空", "travel": "旅行", "automotive": "汽车",
             "event": "漫展", "bird": "鸟类", "flower": "花卉", "pet": "宠物", "other": "其他"}


def detect_cat(path):
    for kw, cat in CAT_RULES:
        if kw.lower() in path.lower():
            return cat
    return "other"


def load_lr_full():
    """Load yellow-labeled + rated photos from LR catalog."""
    if not os.path.exists(LRCAT):
        return []
    tmp = tempfile.NamedTemporaryFile(suffix=".lrcat", delete=False)
    tmp.close()
    shutil.copy2(LRCAT, tmp.name)
    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row
    sql = """SELECT f.baseName, f.extension, i.rating, i.pick, i.colorLabels,
                    fo.pathFromRoot, r.absolutePath as rootPath
             FROM Adobe_images i
             JOIN AgLibraryFile f ON i.rootFile = f.id_local
             JOIN AgLibraryFolder fo ON f.folder = fo.id_local
             JOIN AgLibraryRootFolder r ON fo.rootFolder = r.id_local
             WHERE i.colorLabels = '黄色'"""
    rows = [dict(row) for row in conn.execute(sql)]
    conn.close()
    os.unlink(tmp.name)
    return rows


def find_final_match(lr_entry, event_dir):
    """Find FINAL JPG matching a LR entry in the event directory."""
    fd = event_dir / "05_FINAL"
    if not fd.is_dir():
        return None
    stem = lr_entry["baseName"]

    # Exact match
    for ext in [".jpg", ".jpeg", ".JPG", ".JPEG"]:
        candidate = fd / f"{stem}{ext}"
        if candidate.exists():
            return candidate

    # Fuzzy: stem appears in final filename or vice versa
    for f in sorted(fd.iterdir()):
        if f.suffix.lower() in (".jpg", ".jpeg") and not f.name.startswith("."):
            fstem = f.stem
            if stem in fstem or fstem in stem:
                return f

    return None


def find_event_dir(path_from_root, root_path):
    """Map LR's folder path to NAS event directory."""
    root = (root_path or "").rstrip("/")
    folder = path_from_root or ""

    # Remap old mount points to current NAS
    REMAPS = [
        ("/Volumes/photo/A图片", "/Volumes/home/Photos/A图片"),
        ("/Volumes/photo", "/Volumes/home/Photos"),
    ]

    # Build path from folder structure
    parts = []
    found_root = root
    for old, new in REMAPS:
        if root.startswith(old):
            found_root = root.replace(old, new, 1)
            break

    # Get relative part from root
    rel_root = ""
    for old, new in REMAPS:
        if root.startswith(old):
            rel_root = root[len(old):].lstrip("/")
            break
    if not rel_root:
        # Try to extract meaningful part from root
        for prefix in ["/Volumes/home/Photos/A图片/", "/Volumes/home/"]:
            if found_root.startswith(prefix):
                rel_root = found_root[len(prefix):]
                break

    if rel_root and rel_root != ".":
        parts.append(rel_root)

    for p in folder.split("/"):
        p = p.strip()
        if p and p != ".":
            parts.append(p)

    # Walk NAS to find matching directory
    nas_path = Path(NAS)
    for p in parts:
        candidate = nas_path / p
        if candidate.is_dir():
            nas_path = candidate

    if (nas_path / "05_FINAL").is_dir() or (nas_path / "01_RAW").is_dir():
        return nas_path

    # Fallback: search by year + event in parts
    year_match = re.search(r'(20\d{2})', folder)
    if year_match:
        year = year_match.group(1)
        for part in reversed(parts):
            candidate = Path(NAS) / year / part
            if candidate.is_dir():
                return candidate

    return None


def is_portfolio_photo(entry):
    """Filter out wallpapers, memes, non-photography images."""
    root = (entry.get("rootPath") or "").lower()
    path = (entry.get("pathFromRoot") or "").lower()
    combined = root + path
    # Skip wallpapers, phone screenshots, anime collections
    skip_keywords = ["壁纸", "截图", "二次元", "anime", "meme"]
    for kw in skip_keywords:
        if kw in combined:
            return False
    return True


# ========== SCAN ==========
def cmd_scan():
    lr = {}
    tmp = tempfile.NamedTemporaryFile(suffix=".lrcat", delete=False)
    tmp.close()
    shutil.copy2(LRCAT, tmp.name)
    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row
    for row in conn.execute("""SELECT f.baseName, i.rating, i.pick, i.colorLabels
                                FROM Adobe_images i
                                JOIN AgLibraryFile f ON i.rootFile=f.id_local
                                WHERE i.rating>=3 OR i.colorLabels!=''"""):
        if row["baseName"]:
            lr[row["baseName"]] = {
                "rating": int(row["rating"]) if row["rating"] else 0,
                "flagged": bool(row["pick"]),
                "color": row["colorLabels"] or ""
            }
    conn.close()
    os.unlink(tmp.name)

    colored = sum(1 for v in lr.values() if v["color"])
    print(f"LR中有评分/色标: {len(lr)}条 (其中{colored}条有色标)\n")

    candidates = []
    for yd in sorted(os.listdir(NAS)):
        yp = Path(NAS) / yd
        if not yp.is_dir() or yd == "phonephotos":
            continue
        for evt in sorted(os.listdir(yp)):
            fd = yp / evt / "05_FINAL"
            if not fd.is_dir():
                continue
            for f in sorted(fd.iterdir()):
                if f.name.startswith("."):
                    continue
                if f.suffix.lower() not in (".jpg", ".jpeg"):
                    continue
                info = lr.get(f.stem)
                candidates.append({
                    "evt": f"{yd}/{evt}", "file": f.name, "path": str(f),
                    "cat": detect_cat(str(yp / evt)),
                    "stars": info["rating"] if info else 0,
                    "flag": info["flagged"] if info else False,
                    "color": info["color"] if info else "",
                    "kb": f.stat().st_size // 1024
                })

    by_cat = defaultdict(list)
    for c in candidates:
        by_cat[c["cat"]].append(c)
    for cat in sorted(by_cat):
        items = sorted(by_cat[cat], key=lambda x: (-x["stars"], -x["kb"]))
        rated = sum(1 for i in items if i["stars"] >= 3)
        print(f"  {CAT_NAMES.get(cat, cat)} ({len(items)}张, {rated}已评分):")
        for i, c in enumerate(items[:5]):
            stars = "★" * c["stars"] if c["stars"] else "  "
            tag = ""
            if c["color"] == "黄色":
                tag = "🟡"
            elif c["color"] == "红色":
                tag = "🔴"
            print(f"    {i+1}. {tag}{stars:5s} {c['evt']:35s} {c['file']:25s} {c['kb']:>5d}KB")


# ========== DEPLOY (黄标 → 自动上线) ==========
def cmd_deploy(go=False):
    if not os.path.exists(NAS):
        print("❌ NAS 未挂载: /Volumes/home")
        return

    print("🔍 读取 LR 黄色色标...")
    lr_entries = load_lr_full()
    if not lr_entries:
        print("  ⚠️ 没有找到黄标照片。")
        print("  在LR里给想上线的照片打 黄色色标, 然后重新运行。")
        return

    # Match yellow entries to FINAL JPGs
    matched = []
    unmatched = []
    for entry in lr_entries:
        event_dir = find_event_dir(entry["pathFromRoot"], entry["rootPath"])
        if event_dir and event_dir.is_dir():
            final = find_final_match(entry, event_dir)
            if final:
                matched.append((entry, final, event_dir))
            else:
                unmatched.append((entry, event_dir))

    print(f"  黄标照片: {len(lr_entries)}张")
    # Filter out wallpapers
    lr_entries = [e for e in lr_entries if is_portfolio_photo(e)]
    print(f"  过滤(壁纸等)后: {len(lr_entries)}张")
    print(f"  匹配到FINAL: {len(matched)}张")
    print(f"  未匹配: {len(unmatched)}张")

    if not matched:
        print("\n⚠️ 没有黄标照片能自动匹配到FINAL成片。")
        if unmatched:
            print("  未匹配的事件(可能三星T7离线,或FINAL改名):")
            for entry, evt_dir in unmatched[:10]:
                print(f"    {evt_dir.relative_to(NAS)}/05_FINAL/")
        return

    # Show plan
    by_cat = defaultdict(list)
    for entry, final, evt in matched:
        cat = detect_cat(str(evt))
        by_cat[cat].append((entry, final))

    print(f"\n📦 将要部署 {len(matched)} 张:")
    for cat in sorted(by_cat):
        items = by_cat[cat]
        print(f"\n  {CAT_NAMES.get(cat, cat)} ({len(items)}张):")
        for entry, final in items[:8]:
            stars = "★" * int(entry["rating"]) if entry["rating"] else ""
            print(f"    {stars:5s} {final.name}")
        if len(items) > 8:
            print(f"    ... 还有{len(items)-8}张")

    if not go:
        print(f"\n🔍 DRY RUN — 确认无误后加 --go 执行")
        return

    # ===== EXECUTE =====
    print(f"\n🚀 执行部署...")

    # 1. Copy to images/new/
    img_dir = ROOT / "images" / "new"
    if img_dir.exists():
        shutil.rmtree(img_dir)
    img_dir.mkdir(parents=True)

    for entry, final, evt in matched:
        shutil.copy2(final, img_dir / final.name)

    # 2. Optimize to WebP
    result = []
    for f in sorted(img_dir.iterdir()):
        if f.name.startswith("."):
            continue
        try:
            img = Image.open(f)
            if img.mode in ("RGBA", "P", "CMYK"):
                img = img.convert("RGB")
            orig_w, orig_h = img.size
            orig_kb = f.stat().st_size // 1024

            paths = {}
            sizes_kb = {}
            for size_name, (max_w, quality) in SIZES.items():
                if orig_w > max_w:
                    ratio = max_w / orig_w
                    resized = img.resize((max_w, int(orig_h * ratio)), Image.LANCZOS)
                else:
                    resized = img.copy()
                dst = OPT_DIR / size_name / f"{f.stem}.webp"
                dst.parent.mkdir(parents=True, exist_ok=True)
                resized.save(dst, "WEBP", quality=quality, method=6)
                paths[size_name] = f"optimized/{size_name}/{f.stem}.webp"
                sizes_kb[size_name] = dst.stat().st_size // 1024

            print(f"  ✅ {f.name:30s} {orig_kb:>5d}KB → thumb:{sizes_kb['thumb']:3d}KB")

            # Find event for category
            evt_str = ""
            for entry, final, evt in matched:
                if final.name == f.name:
                    evt_str = str(evt.relative_to(NAS))
                    break

            result.append({
                "title": f.stem,
                "category": detect_cat(evt_str),
                "thumb": paths["thumb"],
                "display": paths["display"],
                "full": paths["full"],
                "thumb_kb": sizes_kb["thumb"],
                "display_kb": sizes_kb["display"],
                "full_kb": sizes_kb["full"],
            })
        except Exception as e:
            print(f"  ❌ {f.name}: {e}")

    # 3. Update gallery.json
    gallery_path = ROOT / "gallery.json"
    with open(gallery_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total_orig = sum(f.stat().st_size for f in img_dir.iterdir() if not f.name.startswith(".")) / 1024 / 1024
    total_opt = sum(r["thumb_kb"] + r["display_kb"] + r["full_kb"] for r in result) / 1024
    print(f"\n  📸 {len(result)}张  |  原图{total_orig:.0f}MB → 优化{total_opt:.0f}MB")
    print(f"  gallery.json 已更新")

    # 4. Git push
    print(f"\n📤 提交到 GitHub...")
    os.chdir(ROOT)
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-m", f"📷 黄标部署: {len(result)}张"], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)
    print(f"\n✅ 完成！等1-2分钟刷新 https://liooo0.github.io/lio-photo-portfolio/")


# ========== ORGANIZE ==========
def cmd_organize(go=False):
    print("NAS目录已标准化(86事件, 01_RAW ~ 05_FINAL)")


# ========== EXIF ==========
def cmd_exif(go=False):
    events = []
    for yd in sorted(os.listdir(NAS)):
        yp = Path(NAS) / yd
        if not yp.is_dir() or yd == "phonephotos":
            continue
        for evt in sorted(os.listdir(yp)):
            ep = yp / evt
            comp = (ep / "03_COMP").is_dir() and any(
                True for _ in (ep / "03_COMP").iterdir() if not _.name.startswith("."))
            cake = (ep / "04_CAKE").is_dir() and any(
                True for _ in (ep / "04_CAKE").iterdir() if not _.name.startswith("."))
            final = (ep / "05_FINAL").is_dir()
            if (comp or cake) and final:
                events.append(f"{yd}/{evt}")

    if not events:
        print("没有走PS/像素蛋糕流程的事件。")
        return

    print(f"检查 {len(events)} 个事件...")
    all_plan = []
    for evt in events:
        ep = Path(NAS) / evt
        fd = ep / "05_FINAL"
        rd = ep / "01_RAW"
        if not rd.is_dir():
            continue
        r = subprocess.run(["exiftool", "-json", "-ISO", "-FileName", str(fd)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode:
            continue
        data = json.loads(r.stdout)
        no_iso = [d for d in data if not d.get("ISO")]
        if not no_iso:
            continue

        raws = sorted([f for f in rd.iterdir()
                       if f.suffix.lower() in RAW_EXTS and not f.name.startswith(".")],
                      key=lambda f: f.name)
        no_iso.sort(key=lambda d: os.path.basename(d["SourceFile"]))
        plan = [(str(raws[i]), entry["SourceFile"])
                for i, entry in enumerate(no_iso) if i < len(raws)]
        all_plan.extend(plan)

        if go:
            for raw, final in plan:
                subprocess.run(
                    ["exiftool", "-overwrite_original", "-tagsfromfile", raw,
                     "-all:all", "-ThumbnailImage", final],
                    capture_output=True, timeout=10)

    print(f"缺EXIF: {len(all_plan)}张" + (" → 已修复" if go else " (dry-run, 加 --go 执行)"))


# ========== MAIN ==========
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "deploy"
    go = "--go" in sys.argv
    {"scan": cmd_scan, "deploy": cmd_deploy, "organize": cmd_organize, "exif": cmd_exif}.get(
        cmd, cmd_deploy)(go)
