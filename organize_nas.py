#!/usr/bin/env python3
"""
NAS 照片整理 — Dry Run 预览 + 实际执行 + 回滚

用法:
  python3 organize_nas.py                  # dry-run 预览
  python3 organize_nas.py --execute        # 实际执行（会自动创建回滚脚本）
  python3 organize_nas.py --rollback FILE  # 用回滚脚本还原

规则:
  raw/ 原图/ 原片/ dng/  →  RAW/          (原始文件)
  LRC导出的 tiff/jpg       →  EDIT/         (调色导出)
  PS六合一大图             →  COMP/         (合成文件, 保留1年)
  像素蛋糕相关             →  CAKE/         (修图中间文件)
  jpg/ 成片/ 散落最终jpg   →  FINAL/        (最终成片)

文件名不动。重名冲突时保留两份，加 _dup 后缀。
"""

import os
import sys
import shutil
import json
import time
from pathlib import Path
from collections import defaultdict

NAS = "/Volumes/home/Photos/A图片"
LOG_FILE = Path(__file__).parent / "organize_log.json"

# Subfolder mappings: (目标, 匹配关键词列表, 分类说明)
RULES = [
    ("RAW",   ["raw", "原图", "原片", "dng"],                        "原始文件"),
    ("EDIT",  ["edit", "调色", "导出", "lrc"],                        "调色导出"),
    ("COMP",  ["六合一", "合成", "stitch", "composite", "comp"],      "PS合成大图"),
    ("CAKE",  ["像素蛋糕", "cake", "pixel", "修图", "retouch"],       "像素蛋糕"),
    ("FINAL", ["jpg", "成片", "output", "final", "final jpg"],        "最终成片"),
]

# Raw file extensions
RAW_EXTS = {".rw2", ".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".raf"}
# Image file extensions
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff", ".tif", ".psd", ".psb"}
# All known file types
KNOWN_EXTS = RAW_EXTS | IMG_EXTS | {".xmp", ".lrcat", ".lrdata", ".mov", ".mp4", ".avi", ".m4v", ".txt", ".docx", ".pdf"}
# Files to NOT move (these stay in event root)
SKIP_NAMES = {".DS_Store", ".keep", ".gitignore", "Thumbs.db"}


def detect_final_name(raw_base, event_dir):
    """Try to find the output filename that corresponds to a raw file.
    Returns list of candidate output names."""
    # Strip common suffixes from raw name
    import re
    clean = re.sub(r'[-_](?:已增强|降噪|NR|edit|调色).*$', '', raw_base, flags=re.IGNORECASE)
    clean = clean.strip('_-')
    return [clean]


def scan_event(event_path):
    """Analyze one event directory, return reorganization plan."""
    event_path = Path(event_path)
    plan = {"moves": [], "creates": [], "deletes": [], "warnings": []}

    # Find all files and their current locations
    all_files = []
    for root, dirs, files in os.walk(event_path):
        # Skip already-organized target dirs
        dirs[:] = [d for d in dirs if d not in {"RAW", "EDIT", "COMP", "CAKE", "FINAL"}]

        for f in files:
            if f in SKIP_NAMES and root == str(event_path):
                continue
            if f.startswith(".") and f not in SKIP_NAMES:
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, event_path)
            ext = os.path.splitext(f)[1].lower()
            plan["all_files"].append({
                "rel": rel,
                "ext": ext,
                "size": os.path.getsize(full),
            })

    return plan


def classify_file(rel_path: str, ext: str) -> str:
    """Classify a file into one of the target folders based on path and extension."""
    rel_lower = rel_path.lower()
    parent_dir = os.path.basename(os.path.dirname(rel_path)).lower()
    # Full ancestor chain for multi-level matching
    ancestors = [p.lower() for p in Path(rel_path).parts[:-1]]

    # --- RAW: always for raw camera files, regardless of location ---
    if ext in RAW_EXTS:
        return "RAW"

    # --- DNG in weird subdirs is still RAW ---
    if ext == ".dng":
        return "RAW"

    # --- TIFF handling ---
    if ext in {".tiff", ".tif"}:
        # Check ancestor chain for composite keywords
        if any(kw in a for a in ancestors for kw in ["6in1", "6in", "六合一", "合成", "stitch", "comp"]):
            return "COMP"
        if any(kw in a for a in ancestors for kw in ["原图", "原片", "dng", "raw"]):
            return "RAW"
        if any(kw in a for a in ancestors for kw in ["蛋糕", "cake", "pixcake"]):
            return "CAKE"
        return "EDIT"

    # --- PSD/PSB always composite ---
    if ext in {".psd", ".psb"}:
        return "COMP"

    # --- JPG/PNG/WebP: check context ---
    if ext in IMG_EXTS - RAW_EXTS - {".tiff", ".tif", ".psd", ".psb"}:
        # Composite patterns
        if any(kw in a for a in ancestors for kw in ["6in1", "6in", "六合一", "合成", "stitch", "comp"]):
            return "COMP"
        # Cake/retouch patterns
        if any(kw in a for a in ancestors for kw in ["蛋糕", "cake", "pixcake", "修图", "retouch"]):
            return "CAKE"
        # Edit/export patterns
        if any(kw in a for a in ancestors for kw in ["edit", "调色", "导出", "lrc", "lr_out"]):
            return "EDIT"
        # Raw patterns — original JPGs in raw dirs
        if any(kw in a for a in ancestors for kw in ["原图", "原片", "dng", "raw", "原"]):
            return "RAW"
        # Final output patterns
        if any(kw in a for a in ancestors for kw in ["jpg", "成片", "output", "final"]):
            return "FINAL"
        # Root-level jpg — FINAL
        return "FINAL"

    # --- Videos stay with originals ---
    if ext in {".mov", ".mp4", ".avi", ".m4v"}:
        return "RAW"

    # Unknown — skip
    return None


def build_plan(nas_base):
    """Walk NAS and build full reorganization plan."""
    nas = Path(nas_base)
    plan = {
        "events": {},  # event -> list of (from_rel, to_rel, action)
        "year_orphans": {},  # year -> list of orphan files at year root
        "phonephotos": {},  # year -> list of phone photos
        "stats": defaultdict(lambda: defaultdict(int)),
        "rollback_commands": [],
    }

    for year_dir in sorted(os.listdir(nas)):
        yp = nas / year_dir
        if not yp.is_dir():
            continue

        if year_dir == "phonephotos":
            plan["phonephotos"] = handle_phonephotos(yp)
            continue

        # Year-level loose files
        year_orphans = []
        for f in sorted(os.listdir(yp)):
            fp = yp / f
            if f in SKIP_NAMES:
                continue
            if fp.is_file():
                ext = fp.suffix.lower()
                target = classify_file(f, ext)
                year_orphans.append({
                    "file": f,
                    "size": fp.stat().st_size,
                    "target": target or "ROOT",
                })
        if year_orphans:
            plan["year_orphans"][year_dir] = year_orphans

        # Event directories
        for evt_dir in sorted(os.listdir(yp)):
            ep = yp / evt_dir
            if not ep.is_dir():
                continue

            event_moves = scan_event_dir(ep)
            if event_moves:
                plan["events"][f"{year_dir}/{evt_dir}"] = event_moves

            # Count stats
            for move in event_moves:
                if "target" in move:
                    plan["stats"][move["target"]][year_dir] += 1

    return plan


def scan_event_dir(event_path):
    """Scan one event directory, classify all files, produce move list."""
    event_path = Path(event_path)
    moves = []
    dirs_to_clean = set()

    for root, dirs, files in os.walk(event_path):
        # Track subdirs for cleanup
        rel_root = os.path.relpath(root, event_path)

        for f in files:
            if f.startswith("."):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, event_path)
            ext = os.path.splitext(f)[1].lower()

            # Skip if already in a target folder
            parts = Path(rel).parts
            if len(parts) > 1 and parts[0] in {"RAW", "EDIT", "COMP", "CAKE", "FINAL"}:
                continue

            target = classify_file(rel, ext)
            if target is None:
                continue

            # Avoid moving files from root that should stay
            if rel_root == "." and target == "FINAL" and ext not in IMG_EXTS:
                continue

            # Determine destination
            dest_rel = f"{target}/{f}"

            # Handle conflicts
            dest_abs = event_path / dest_rel
            if dest_abs.exists() and os.path.getsize(dest_abs) == os.path.getsize(full):
                # Same size = same file, skip
                continue
            elif dest_abs.exists():
                # Different, rename
                stem, ext_orig = os.path.splitext(f)
                dest_rel = f"{target}/{stem}_dup{ext_orig}"
                moves.append({
                    "from": rel,
                    "to": dest_rel,
                    "size": os.path.getsize(full),
                    "target": target,
                    "note": "重名冲突，已加 _dup 后缀",
                })
            else:
                moves.append({
                    "from": rel,
                    "to": dest_rel,
                    "size": os.path.getsize(full),
                    "target": target,
                })

            # Mark parent dir for potential cleanup
            parent = os.path.dirname(rel)
            if parent and parent != "." and parent not in {"RAW", "EDIT", "COMP", "CAKE", "FINAL"}:
                dirs_to_clean.add(parent)

    # After moving all files, the old subdirs can be cleaned
    moves.append({
        "_cleanup": list(dirs_to_clean),
    })

    return moves


def handle_phonephotos(phonepath):
    """Plan for phonephotos: keep structure but organize by year."""
    plan = {}
    for year in sorted(os.listdir(phonepath)):
        yp = phonepath / year
        if not yp.is_dir():
            continue
        files = []
        for f in sorted(os.listdir(yp)):
            if f.startswith("."):
                continue
            fp = yp / f
            if fp.is_file():
                ext = fp.suffix.lower()
                target = classify_file(f, ext)
                files.append({
                    "file": f,
                    "size": fp.stat().st_size,
                    "target": target or "ROOT",
                })
        if files:
            plan[year] = files
    return plan


def print_dry_run(plan):
    """Pretty-print the reorganization plan."""
    print("=" * 80)
    print(f"📋 NAS 照片整理 — DRY RUN 预览")
    print(f"   源: {NAS}")
    print("=" * 80)

    # Summary by target
    total_files = sum(sum(years.values()) for years in plan["stats"].values())
    print(f"\n📊 分类汇总 (共 {total_files} 个文件):")
    for target, years in sorted(plan["stats"].items()):
        total = sum(years.values())
        bar = "█" * min(total, 60)
        print(f"  {target:10s} {total:5d} 个  {bar}")

    # Event details
    print(f"\n{'—' * 60}")
    print(f"📁 事件目录详情 ({len(plan['events'])} 个事件)")
    print(f"{'—' * 60}")

    for event_name in sorted(plan["events"].keys()):
        moves = [m for m in plan["events"][event_name] if "from" in m]
        if not moves:
            continue
        print(f"\n  {event_name} ({len(moves)} 个文件):")

        # Group by target
        by_target = defaultdict(list)
        for m in moves:
            by_target[m["target"]].append(m)

        for target in ["RAW", "EDIT", "COMP", "CAKE", "FINAL"]:
            items = by_target.get(target, [])
            if items:
                size_total = sum(m["size"] for m in items)
                print(f"    → {target}/  {len(items):3d}个  ({size_total/1024/1024:.1f}MB)")
                for m in items[:3]:
                    note = f"  ⚠️ {m['note']}" if "note" in m else ""
                    print(f"        {m['from']} → {m['to']}{note}")
                if len(items) > 3:
                    print(f"        ... 还有 {len(items)-3} 个")

    # Year orphans
    if plan["year_orphans"]:
        print(f"\n{'—' * 60}")
        print(f"📁 年份根目录散文件")
        print(f"{'—' * 60}")
        for year, files in sorted(plan["year_orphans"].items()):
            total = len(files)
            targets = defaultdict(int)
            for f in files:
                targets[f["target"]] += 1
            print(f"\n  {year}/ ({total} 个散文件):")
            for target, count in sorted(targets.items()):
                print(f"    → 建议: 归入对应事件的 {target}/ 或新建 _unsorted/{target}/")

    # Phonephotos
    if plan["phonephotos"]:
        print(f"\n{'—' * 60}")
        print(f"📱 phonephotos (手机照片)")
        print(f"{'—' * 60}")
        for year, files in sorted(plan["phonephotos"].items()):
            total = len(files)
            targets = defaultdict(int)
            for f in files:
                targets[f["target"]] += 1
            print(f"  {year}: {total} 个文件")
            for target, count in sorted(targets.items()):
                print(f"    {target}: {count}")

    # Bottom
    print(f"\n{'=' * 80}")
    print("⚠️  以上为预览，未实际移动任何文件")
    print("   执行: python3 organize_nas.py --execute")
    print("   回滚: python3 organize_nas.py --rollback <log_file>")
    print("=" * 80)


def execute_plan(plan):
    """Actually move files and create rollback log."""
    log = {"executed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "operations": [], "errors": []}
    total = 0

    for event_name, moves in plan["events"].items():
        event_path = Path(NAS) / event_name

        # Create target dirs
        for target in ["RAW", "EDIT", "COMP", "CAKE", "FINAL"]:
            (event_path / target).mkdir(exist_ok=True)

        for move in moves:
            if "_cleanup" in move:
                continue  # Skip cleanup marker

            src = event_path / move["from"]
            dst = event_path / move["to"]

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                log["operations"].append({
                    "event": event_name,
                    "from": str(src),
                    "to": str(dst),
                    "size": move["size"],
                })
                total += 1
                print(f"  ✅ {move['from']:50s} → {move['to']}")
            except Exception as e:
                log["errors"].append({
                    "event": event_name,
                    "from": str(src),
                    "to": str(dst),
                    "error": str(e),
                })
                print(f"  ❌ {move['from']}: {e}")

        # Clean up empty old subdirs
        for old_dir in [m for m in moves if "_cleanup" in m]:
            for dir_name in reversed(sorted(old_dir["_cleanup"])):
                dir_path = event_path / dir_name
                try:
                    if dir_path.exists() and not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        print(f"  🗑️  删除空目录: {dir_name}")
                except:
                    pass

    # Save log
    log["total_moved"] = total
    log["errors_count"] = len(log["errors"])
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 移动完成: {total} 个文件")
    if log["errors"]:
        print(f"⚠️  {len(log['errors'])} 个错误")
    print(f"📝 回滚日志: {LOG_FILE}")
    print(f"   回滚命令: python3 organize_nas.py --rollback {LOG_FILE}")

    return log


def rollback(log_file):
    """Undo all moves from a log file."""
    with open(log_file) as f:
        log = json.load(f)

    print(f"🔄 回滚 {len(log['operations'])} 个操作...")
    undone = 0
    for op in reversed(log["operations"]):
        src = Path(op["to"])  # Swapped: move back
        dst = Path(op["from"])
        try:
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                undone += 1
                if undone % 50 == 0:
                    print(f"  已回滚 {undone}/{len(log['operations'])}...")
        except Exception as e:
            print(f"  ❌ 回滚失败 {op['to']} → {op['from']}: {e}")

    print(f"✅ 回滚完成: {undone} 个文件已还原")
    return undone


def main():
    if "--rollback" in sys.argv:
        idx = sys.argv.index("--rollback")
        log_file = sys.argv[idx + 1]
        rollback(log_file)
        return

    execute = "--execute" in sys.argv

    if not os.path.exists(NAS):
        print(f"❌ NAS 未挂载: {NAS}")
        sys.exit(1)

    print("🔄 扫描 NAS...")
    plan = build_plan(NAS)
    print_dry_run(plan)

    if execute:
        print(f"\n⚠️  确认执行？ (输入 yes 继续): ", end="", flush=True)
        answer = input().strip().lower()
        if answer == "yes":
            execute_plan(plan)
        else:
            print("已取消")


if __name__ == "__main__":
    main()
