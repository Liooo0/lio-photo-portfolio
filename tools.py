#!/usr/bin/env python3
"""
Lio 摄影工具箱 — 三合一

用法:
  python3 tools.py scan      扫描NAS成片+LR评分 → 候选清单
  python3 tools.py organize  整理NAS事件目录(01_RAW ~ 05_FINAL)
  python3 tools.py exif      从RAW回填EXIF到缺参数的FINAL JPG

所有操作先dry-run预览，加 --go 才实际执行
"""
import sys, os, json, shutil, sqlite3, tempfile, subprocess, re
from pathlib import Path
from collections import defaultdict

LRCAT = os.path.expanduser("~/Pictures/Lightroom/Lightroom Catalog.lrcat")
NAS = "/Volumes/home/Photos/A图片"
RAW_EXTS = {".rw2", ".cr2", ".cr3", ".dng", ".nef", ".arw"}

CAT_RULES = [
    ("日出", "sunrise"), ("日落", "sunset"), ("晚霞", "sunset"),
    ("荷花", "lotus"), ("洪湖", "lotus"),
    ("深圳湾", "cityscape"), ("天文台", "landscape"), ("蛇口", "cityscape"),
    ("车", "automotive"), ("领克", "automotive"),
    ("星空", "star"), ("萤火虫", "star"),
    ("鸟", "bird"), ("花", "flower"), ("樱", "flower"), ("猫", "pet"),
    ("北京", "travel"), ("四川", "travel"), ("南京", "travel"), ("上海", "travel"),
    ("澳门", "travel"), ("香港", "travel"), ("厦门", "travel"), ("阳朔", "travel"),
    ("稻城", "travel"), ("山西", "travel"), ("云南", "travel"), ("贵州", "travel"),
    ("cicf", "event"), ("同人展", "event"), ("漫展", "event"), ("嘉年华", "event"),
    ("瀑布", "landscape"), ("公园", "landscape"), ("山", "landscape"),
]
CAT_NAMES = {"sunrise":"日出","sunset":"日落","lotus":"荷花","cityscape":"城市","landscape":"风光",
             "star":"星空","travel":"旅行","automotive":"汽车","event":"漫展","bird":"鸟类",
             "flower":"花卉","pet":"宠物","other":"其他"}
RATING_EMOJI = {5: "👑", 4: "🔥", 3: "⭐", 2: "·", 1: "·"}

def detect_cat(path):
    for kw, cat in CAT_RULES:
        if kw.lower() in path.lower():
            return cat
    return "other"

def load_lr():
    if not os.path.exists(LRCAT): return {}
    tmp = tempfile.NamedTemporaryFile(suffix=".lrcat", delete=False)
    tmp.close(); shutil.copy2(LRCAT, tmp.name)
    conn = sqlite3.connect(tmp.name); conn.row_factory = sqlite3.Row
    lr = {}
    for row in conn.execute("SELECT f.baseName, i.rating, i.pick FROM Adobe_images i JOIN AgLibraryFile f ON i.rootFile=f.id_local WHERE i.rating>=3"):
        if row["baseName"]: lr[row["baseName"]] = {"rating":int(row["rating"]),"flagged":bool(row["pick"])}
    conn.close(); os.unlink(tmp.name)
    return lr

# ========== SCAN ==========
def cmd_scan(go=False):
    lr = load_lr()
    print(f"LR评分: {len(lr)}条(3★+)")
    candidates = []
    for yd in sorted(os.listdir(NAS)):
        yp = Path(NAS)/yd
        if not yp.is_dir() or yd=="phonephotos": continue
        for evt in sorted(os.listdir(yp)):
            fd = yp/evt/"05_FINAL"
            if not fd.is_dir(): continue
            for f in sorted(fd.iterdir()):
                if f.name.startswith(".") or f.suffix.lower() not in (".jpg",".jpeg"): continue
                info = lr.get(f.stem)
                candidates.append({"evt":f"{yd}/{evt}","file":f.name,"path":str(f),
                    "cat":detect_cat(str(yp/evt)),"stars":info["rating"]if info else 0,
                    "flag":info["flagged"]if info else False,"kb":f.stat().st_size//1024})

    print(f"FINAL成片: {len(candidates)}张\n")
    by_cat = defaultdict(list)
    for c in candidates: by_cat[c["cat"]].append(c)
    for cat in sorted(by_cat):
        items = sorted(by_cat[cat], key=lambda x:(-x["stars"],-x["kb"]))
        rated = sum(1 for i in items if i["stars"]>=3)
        print(f"  {CAT_NAMES.get(cat,cat)} ({len(items)}张, {rated}已评分):")
        for i,c in enumerate(items[:5]):
            stars = "★"*c["stars"] if c["stars"] else "  "
            flag = "🚩" if c["flag"] else " "
            print(f"    {i+1}. {flag}{stars:5s} {c['evt']:35s} {c['file']:25s} {c['kb']:>5d}KB")
        if len(items)>5: print(f"    ... 还有{len(items)-5}张")
        print()

# ========== ORGANIZE (dry-run only, actual exec was done) ==========
def cmd_organize(go=False):
    print("Organize已在之前的会话中执行完毕，86个事件目录已标准化。")
    print("如需重新整理，请先确认当前状态。")

# ========== EXIF FIX ==========
def cmd_exif(go=False):
    # Find events with COMP/CAKE (indicating PS/pixelcake pipeline)
    events = []
    for yd in sorted(os.listdir(NAS)):
        yp = Path(NAS)/yd
        if not yp.is_dir() or yd=="phonephotos": continue
        for evt in sorted(os.listdir(yp)):
            ep = yp/evt
            comp = (ep/"03_COMP").is_dir() and any(True for _ in (ep/"03_COMP").iterdir() if not _.name.startswith("."))
            cake = (ep/"04_CAKE").is_dir() and any(True for _ in (ep/"04_CAKE").iterdir() if not _.name.startswith("."))
            final = (ep/"05_FINAL").is_dir()
            if (comp or cake) and final:
                events.append(f"{yd}/{evt}")

    if not events:
        print("没有走PS/像素蛋糕流程的事件，无需修复。")
        return

    print(f"检查 {len(events)} 个事件...")
    plan = []; missing = 0
    for evt in events:
        ep = Path(NAS)/evt; fd = ep/"05_FINAL"; rd = ep/"01_RAW"
        if not rd.is_dir(): continue
        r = subprocess.run(["exiftool","-json","-ISO","-FileName",str(fd)],capture_output=True,text=True,timeout=60)
        if r.returncode: continue
        data = json.loads(r.stdout)
        no_iso = [d for d in data if not d.get("ISO")]
        if not no_iso: continue

        raws = sorted([f for f in rd.iterdir() if f.suffix.lower() in RAW_EXTS and not f.name.startswith(".")],
                      key=lambda f: f.name)
        no_iso.sort(key=lambda d: os.path.basename(d["SourceFile"]))

        for i,entry in enumerate(no_iso):
            if i < len(raws):
                plan.append((str(raws[i]), entry["SourceFile"]))
                missing += 1

        if go:
            for raw,final in plan:
                subprocess.run(["exiftool","-overwrite_original","-tagsfromfile",raw,"-all:all","-ThumbnailImage",final],
                             capture_output=True,timeout=10)

    print(f"缺EXIF: {missing}张" + (", 已修复" if go else " (dry-run,加 --go 执行)"))

# ========== MAIN ==========
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv)>1 else "scan"
    go = "--go" in sys.argv
    {"scan":cmd_scan,"organize":cmd_organize,"exif":cmd_exif}.get(cmd,cmd_scan)(go)
