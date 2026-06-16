#!/usr/bin/env python3
"""
从 RAW 回填 EXIF 到成片 JPG（只修复丢失参数的）

匹配策略（按优先级）:
  1. 同名匹配: RAW/P1001234.RW2 ↔ FINAL/P1001234.JPG
  2. 时间排序: 按拍摄时间排序后按序配对
  3. EDIT中转: RAW → EDIT(JPG,有EXIF) → FINAL(JPG,丢EXIF)
  4. 跳过: 无法确定配对的

用法:
  python3 fix_exif.py                    # dry-run 预览
  python3 fix_exif.py --execute          # 实际执行

依赖: brew install exiftool
"""
import os, sys, json, subprocess, re, time
from pathlib import Path
from collections import defaultdict

NAS = "/Volumes/home/Photos/A图片"
LOG_FILE = Path(__file__).parent / "exif_fix_log.json"


def get_exif(filepath):
    """Get key EXIF fields as dict. Returns None on failure."""
    try:
        out = subprocess.check_output(
            ["exiftool", "-json", "-DateTimeOriginal", "-ISO", "-FNumber",
             "-ExposureTime", "-FocalLength", "-LensModel", "-Make", "-Model",
             "-Artist", "-Copyright", "-LensID",
             filepath],
            timeout=5, stderr=subprocess.DEVNULL
        )
        data = json.loads(out)
        if data:
            return data[0]
    except:
        pass
    return None


def has_camera_exif(filepath):
    """Check if a JPG has camera EXIF (not just software-added)."""
    exif = get_exif(filepath)
    if not exif:
        return False
    # Camera EXIF has Make/Model and DateTimeOriginal
    return bool(exif.get("Make") or exif.get("CameraModelName"))


def is_missing_exif(filepath):
    """Return True if file is JPG and missing camera parameters."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        return False
    exif = get_exif(filepath)
    if not exif:
        return True  # Can't read = probably missing
    # Missing: no camera model, ISO, aperture
    has_camera = bool(exif.get("ISO") or exif.get("FNumber") or exif.get("ExposureTime"))
    return not has_camera


def find_raw_match(raw_files, final_path, event_dir):
    """Find which RAW file corresponds to this FINAL file."""
    final_name = os.path.splitext(os.path.basename(final_path))[0]

    # Strategy 1: Same base filename
    for raw in raw_files:
        raw_base = os.path.splitext(os.path.basename(raw))[0]
        # Clean suffixes from raw name
        clean = re.sub(r'[-_](?:已增强|降噪|NR).*$', '', raw_base, flags=re.IGNORECASE)
        clean = clean.strip('_-')
        if clean == final_name or raw_base == final_name:
            return raw

    # Strategy 2: FINAL has camera-original name embedded
    # e.g. "2023_07_04_13_21_IMG_3013" → extract "IMG_3013"
    m = re.search(r'(?:IMG_\d+|P\d+|_\d+)(?:[-_].*)?$', final_name)
    if m:
        candidate = m.group(0)
        for raw in raw_files:
            raw_base = os.path.splitext(os.path.basename(raw))[0]
            if candidate in raw_base or raw_base in candidate:
                return raw

    # Strategy 3: Try matching via EDIT dir (LR export has EXIF intact)
    edit_dir = os.path.join(event_dir, "02_EDIT")
    if os.path.isdir(edit_dir):
        for edit_file in os.listdir(edit_dir):
            if edit_file.startswith("."):
                continue
            edit_base = os.path.splitext(edit_file)[0]
            if edit_base == final_name or edit_base in final_name or final_name in edit_base:
                # Found matching EDIT file — now match EDIT back to RAW
                edit_path = os.path.join(edit_dir, edit_file)
                edit_exif = get_exif(edit_path)
                if edit_exif and edit_exif.get("DateTimeOriginal"):
                    dt = edit_exif["DateTimeOriginal"]
                    for raw in raw_files:
                        raw_exif = get_exif(raw)
                        if raw_exif and raw_exif.get("DateTimeOriginal") == dt:
                            return raw
                # Fallback: EDIT filename might contain camera original name
                m2 = re.search(r'(?:IMG_\d+|P\d+|_\d+)', edit_base)
                if m2:
                    for raw in raw_files:
                        if m2.group(0) in os.path.basename(raw):
                            return raw

    return None


def scan_and_match():
    """Walk NAS, match RAW→FINAL, return copy pairs."""
    pairs = []
    stats = {"total_events": 0, "total_raw": 0, "total_final": 0,
             "matched": 0, "already_ok": 0, "skipped": 0}

    for year_dir in sorted(os.listdir(NAS)):
        yp = Path(NAS) / year_dir
        if not yp.is_dir() or year_dir == "phonephotos":
            continue

        for evt in sorted(os.listdir(yp)):
            ep = yp / evt
            if not ep.is_dir():
                continue

            raw_dir = ep / "01_RAW"
            final_dir = ep / "05_FINAL"

            if not raw_dir.is_dir() or not final_dir.is_dir():
                continue

            stats["total_events"] += 1

            # Collect RAW files (only actual camera raw, not JPG copies)
            raw_files = []
            for f in sorted(raw_dir.iterdir()):
                if f.name.startswith("."):
                    continue
                ext = f.suffix.lower()
                if ext in (".rw2", ".cr2", ".cr3", ".dng", ".nef", ".arw"):
                    raw_files.append(str(f))
            stats["total_raw"] += len(raw_files)

            if not raw_files:
                continue

            # Collect FINAL files
            final_files = [str(f) for f in sorted(final_dir.iterdir())
                           if not f.name.startswith(".") and f.suffix.lower() in (".jpg", ".jpeg")]

            for fp in final_files:
                stats["total_final"] += 1
                if is_missing_exif(fp):
                    match = find_raw_match(raw_files, fp, str(ep))
                    if match:
                        pairs.append((match, fp))
                        stats["matched"] += 1
                    else:
                        stats["skipped"] += 1
                else:
                    stats["already_ok"] += 1

    return pairs, stats


def print_dry_run(pairs, stats):
    print("=" * 70)
    print("📸 EXIF 回填 — DRY RUN")
    print("=" * 70)
    print(f"  扫描事件: {stats['total_events']} 个")
    print(f"  总 RAW: {stats['total_raw']}  总 FINAL: {stats['total_final']}")
    print(f"  已含 EXIF (跳过): {stats['already_ok']}")
    print(f"  将修复: {stats['matched']}")
    print(f"  无法匹配 (需手动): {stats['skipped']}")
    print()

    if stats["matched"] == 0:
        print("✅ 所有成片都已包含相机 EXIF，无需修复。")
        return

    # Group by event
    by_event = defaultdict(list)
    for raw, final in pairs:
        # Extract event name from path
        rel = os.path.relpath(final, NAS)
        parts = rel.split(os.sep)
        event = os.path.join(parts[0], parts[1])  # year/eventname
        by_event[event].append((raw, final))

    print(f"将修复 {len(by_event)} 个事件:")
    for event in sorted(by_event.keys()):
        plist = by_event[event]
        print(f"\n  {event} ({len(plist)} 张):")
        for raw, final in plist[:5]:
            raw_name = os.path.basename(raw)
            final_name = os.path.basename(final)
            # Show what EXIF will be copied
            raw_exif = get_exif(raw)
            if raw_exif:
                iso = raw_exif.get("ISO", "?")
                fn = raw_exif.get("FNumber", "?")
                print(f"    {final_name:30s} ← {raw_name:35s}  ISO{iso} f/{fn}")
        if len(plist) > 5:
            print(f"    ... 还有 {len(plist)-5} 张")

    if stats["skipped"] > 0:
        print(f"\n⚠️  {stats['skipped']} 张无法匹配，请看上面exif_todo")

    print(f"\n{'=' * 70}")
    print("执行: python3 fix_exif.py --execute")


def execute_fix(pairs, stats):
    print(f"🔄 修复 {stats['matched']} 张照片...")
    done = 0
    errors = []
    log = []

    for raw, final in pairs:
        try:
            # Copy all EXIF tags from RAW to FINAL (excluding thumbnail/image data)
            subprocess.check_output(
                ["exiftool", "-overwrite_original",
                 "-tagsfromfile", raw,
                 "-all:all",
                 "-ThumbnailImage",  # skip thumbnail
                 "-PreviewImage",     # skip preview
                 final],
                timeout=10, stderr=subprocess.PIPE
            )
            log.append({"raw": raw, "final": final, "status": "ok"})
            done += 1
            if done % 20 == 0:
                print(f"  ... {done}/{stats['matched']}")
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode() if e.stderr else str(e)
            errors.append({"raw": raw, "final": final, "error": err_msg})
            print(f"  ❌ {os.path.basename(final)}: {err_msg[:80]}")

    # Save log
    with open(LOG_FILE, "w") as f:
        json.dump({"done": done, "errors": errors, "log": log}, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 修复: {done} 张")
    if errors:
        print(f"❌ 错误: {len(errors)} 张")
        for e in errors:
            print(f"   {os.path.basename(e['final'])}: {e['error'][:100]}")


def main():
    pairs, stats = scan_and_match()

    if "--execute" in sys.argv:
        execute_fix(pairs, stats)
    else:
        print_dry_run(pairs, stats)


if __name__ == "__main__":
    main()
