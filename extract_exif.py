#!/usr/bin/env python3
"""
从 images/ 原图提取 EXIF + 拍摄地点，合并进 gallery.json

用法:  python3 extract_exif.py
       (若环境 PYTHONPATH 被污染, 脚本会自动用干净环境重启自己)

依赖:  仅 PIL (系统自带 python3 即可), 不需要 exifread/exiftool

规则:
  - 有拍摄参数(光圈/快门/ISO) → 写入 exif 对象; 没有 → 不写 exif 字段
  - EXIF 含 GPS → 坐标写入 geo 字段 {"lat":..,"lng":..} (机位地图用),
    并用高德逆地理编码成地点名 (AMAP_KEY 读环境变量或 ~/weather-api-backend/.env)
  - 无 GPS → location/geo 保留 gallery.json 里已有的手补值, 没有则留空
  - gallery.json 原有字段/顺序全部保留
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# --- 防御: PYTHONPATH 被 Hermes venv 污染时用干净环境重启 ---
_pp = os.environ.get("PYTHONPATH", "")
if "hermes" in _pp:
    clean = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    os.execve(sys.executable, [sys.executable] + sys.argv, clean)

from PIL import Image  # noqa: E402

ROOT = Path(__file__).parent
IMAGES_DIR = ROOT / "images"
GALLERY = ROOT / "gallery.json"
AMAP_ENV_FILE = Path.home() / "weather-api-backend" / ".env"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# 机型 → 友好名
CAMERA_NAMES = {
    "DC-S5M2": "Panasonic S5II",
    "Canon EOS 800D": "Canon 800D",
}
# 无 FocalLengthIn35mmFilm 标签时, 按机型换算等效焦距的裁切系数
CROP_FACTORS = {
    "DC-S5M2": 1.0,       # 全画幅
    "Canon EOS 800D": 1.6,  # APS-C
}


def find_source(title, category):
    """把 gallery.json 条目映射回 images/ 里的原图。"""
    candidates = [IMAGES_DIR / category / title, IMAGES_DIR / title]
    for stem in candidates:
        for ext in IMG_EXTS:
            for case in (ext, ext.upper()):
                p = stem.parent / (stem.name + case)
                if p.exists():
                    return p
    # 兜底: 全库按文件名找
    for p in IMAGES_DIR.rglob(title + ".*"):
        if p.suffix.lower() in IMG_EXTS:
            return p
    return None


def exif_tags(path):
    """读 EXIF, 返回 {标签名: 值} (IFD0 + Exif IFD + GPS IFD)。"""
    from PIL.ExifTags import TAGS, GPSTAGS

    try:
        im = Image.open(path)
        ex = im.getexif()
    except Exception as e:
        print(f"  ⚠️  无法读取: {path.name} ({e})")
        return None
    tags = {}
    for k, v in ex.items():
        tags[TAGS.get(k, hex(k))] = v
    # Exif IFD 用主 TAGS 表; GPS IFD 的标签 ID (1=LatRef,2=Lat,3=LngRef,4=Lng...)
    # 不在主 TAGS 表里, 必须用 GPSTAGS, 否则会变成 '0x2' 之类的键导致解析不到
    for ifd_id, mapping in ((0x8769, TAGS), (0x8825, GPSTAGS)):
        try:
            sub = ex.get_ifd(ifd_id)
        except Exception:
            sub = None
        if sub:
            for k, v in sub.items():
                tags[mapping.get(k, hex(k))] = v
    return tags


def fmt_shutter(t):
    try:
        t = float(t)
    except (TypeError, ValueError):
        return None
    if t <= 0:
        return None
    if t < 1:
        return f"1/{round(1 / t)}s"
    return f"{t:.0f}s" if abs(t - round(t)) < 0.05 else f"{t:.1f}s"


def clean_lens(raw):
    if not raw:
        return ""
    s = str(raw)
    s = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", s)  # "28 - 70mm" → "28-70mm"
    if "|" in s:  # "100-400mm ... | Contemporary 020" → 去掉系列尾巴
        head = s.split("|")[0].strip()
        return "Sigma " + head if head else s.strip()
    return s.strip()


def amap_key():
    key = os.environ.get("AMAP_KEY", "").strip()
    if key:
        return key
    try:
        for line in AMAP_ENV_FILE.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*AMAP_KEY\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip("\"'")
    except OSError:
        pass
    return ""


def reverse_geocode(lat, lon):
    """高德逆地理: 坐标 → 地点名。失败/无 key 返回空串。"""
    key = amap_key()
    if not key:
        print("  ⚠️  有 GPS 但没有 AMAP_KEY, location 留空")
        return ""
    url = (
        "https://restapi.amap.com/v3/geocode/regeo?output=JSON"
        f"&key={urllib.parse.quote(key)}&location={lon:.6f},{lat:.6f}"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "1":
            return data.get("regeocode", {}).get("formatted_address", "") or ""
        print(f"  ⚠️  高德返回异常: {data.get('info')}")
    except Exception as e:
        print(f"  ⚠️  高德请求失败: {e}")
    return ""


def gps_to_decimal(tags):
    def conv(v):
        try:
            d, m, s = v
            return float(d) + float(m) / 60 + float(s) / 3600
        except Exception:
            return None

    lat = conv(tags.get("GPSLatitude"))
    lon = conv(tags.get("GPSLongitude"))
    if lat is None or lon is None:
        return None
    if str(tags.get("GPSLatitudeRef", "N")).upper().startswith("S"):
        lat = -lat
    if str(tags.get("GPSLongitudeRef", "E")).upper().startswith("W"):
        lon = -lon
    return lat, lon


def build_exif(tags):
    """从原始标签构造 exif 对象; 无拍摄参数返回 None。"""
    fnum = tags.get("FNumber")
    shutter = fmt_shutter(tags.get("ExposureTime"))
    iso = tags.get("ISOSpeedRatings")
    if isinstance(iso, (list, tuple)):
        iso = iso[0]
    focal = tags.get("FocalLength")
    if not any([fnum, shutter, iso, focal]):
        return None

    model = str(tags.get("Model", "")).strip()
    out = {}
    if model:
        out["camera"] = CAMERA_NAMES.get(model, model)
    lens = clean_lens(tags.get("LensModel"))
    if lens:
        out["lens"] = lens
    if fnum:
        out["aperture"] = f"f/{float(fnum):g}"
    if shutter:
        out["shutter"] = shutter
    if iso:
        out["iso"] = int(iso)
    if focal:
        focal = int(round(float(focal)))
        out["focal_mm"] = focal
        equiv = tags.get("FocalLengthIn35mmFilm")
        if not equiv:
            crop = CROP_FACTORS.get(model, 1.0)
            equiv = round(focal * crop)
        out["focal_equiv_mm"] = int(equiv)
    taken = tags.get("DateTimeOriginal")
    if taken:
        m = re.match(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2})", str(taken))
        if m:
            out["taken"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}"
    return out or None


def main():
    gallery = json.loads(GALLERY.read_text(encoding="utf-8"))
    n_with, n_without = 0, 0
    for entry in gallery:
        src = find_source(entry.get("title", ""), entry.get("category", ""))
        exif_obj = None
        gps = None
        location = ""
        if src is None:
            print(f"  ⚠️  找不到原图: {entry.get('title')} (跳过 EXIF)")
        else:
            tags = exif_tags(src)
            if tags is not None:
                exif_obj = build_exif(tags)
                gps = gps_to_decimal(tags)
                if gps:
                    location = reverse_geocode(*gps)
        if exif_obj:
            entry["exif"] = exif_obj
            n_with += 1
            eq = exif_obj.get("focal_equiv_mm", "")
            print(f"  ✅ {entry['title']:12s} {exif_obj.get('aperture', '?')} "
                  f"{exif_obj.get('shutter', '?')} ISO{exif_obj.get('iso', '?')} "
                  f"{eq}mm {exif_obj.get('camera', '')}")
        else:
            entry.pop("exif", None)
            n_without += 1
            print(f"  ❌ {entry['title']:12s} 无拍摄 EXIF")
        if gps:
            # EXIF GPS → 坐标给机位地图, 地点名给 lightbox
            entry["geo"] = {"lat": round(gps[0], 6), "lng": round(gps[1], 6)}
            entry["location"] = location or entry.get("location", "")
            print(f"  📍 {entry['title']:12s} GPS {gps[0]:.6f},{gps[1]:.6f} "
                  f"→ {entry['location'] or '(无地点名, 可手补)'}")
        else:
            # 无 GPS: 不覆盖手补的 location/geo, 仅保证字段存在
            entry.setdefault("location", "")

    with open(GALLERY, "w", encoding="utf-8") as f:
        json.dump(gallery, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n完成: {len(gallery)} 张 → {n_with} 有EXIF, {n_without} 无EXIF")


if __name__ == "__main__":
    main()
