#!/usr/bin/env python3
"""
extract_exif.py GPS→geo 链路回归测试（任务6 机位地图的数据基础）。

背景：PIL 的 GPS IFD 标签 ID（1=LatRef, 2=Lat, 3=LngRef, 4=Lng）不在主
ExifTags.TAGS 表里，必须用 GPSTAGS 映射，否则真实带 GPS 的照片永远写不进
geo 字段。本测试用合成 GPS EXIF 图验证全链路，防回归。

用法:  env -u PYTHONPATH /usr/bin/python3 tests/extract_gps_test.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
import PIL.ExifTags as ET  # noqa: E402
from PIL.ExifTags import IFD  # noqa: E402
import extract_exif as X  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  → {extra}" if extra else ""))
    if not cond:
        failures.append(name)


def make_gps_image(path, lat=(22, 32, 35.16), lng=(114, 3, 28.44),
                   lat_ref="N", lng_ref="E"):
    """合成一张带 GPS + 拍摄参数 EXIF 的测试图。"""
    im = Image.new("RGB", (100, 80), (30, 60, 90))
    ex = im.getexif()
    gps = {v: k for k, v in ET.GPSTAGS.items()}
    ex.get_ifd(IFD.GPSInfo).update({
        gps["GPSLatitudeRef"]: lat_ref,
        gps["GPSLatitude"]: lat,
        gps["GPSLongitudeRef"]: lng_ref,
        gps["GPSLongitude"]: lng,
    })
    tags = {v: k for k, v in ET.TAGS.items()}
    ex[tags["Model"]] = "DC-S5M2"
    ex[tags["FNumber"]] = 2.8
    ex[tags["ExposureTime"]] = 0.0005
    ex[tags["ISOSpeedRatings"]] = 100
    ex[tags["FocalLength"]] = 70
    ex[tags["FocalLengthIn35mmFilm"]] = 70
    ex.get_ifd(IFD.Exif)[tags["DateTimeOriginal"]] = "2025:06:25 19:05:00"
    im.save(path, exif=ex)


def main():
    gallery_path = ROOT / "gallery.json"
    bak = gallery_path.read_text(encoding="utf-8")
    tmp_img = ROOT / "images" / "new" / "__gps_test__.jpg"
    tmp_img.parent.mkdir(exist_ok=True)

    try:
        make_gps_image(tmp_img)

        # --- 1) 标签映射：GPS 标签名必须能解析出来（GPSTAGS 回归） ---
        print("\n[1] EXIF 标签映射")
        tags = X.exif_tags(tmp_img)
        check("GPSLatitude 键存在", tags is not None and "GPSLatitude" in tags,
              "键: " + ", ".join(sorted(k for k in (tags or {}) if "GPS" in str(k))))
        check("GPSLongitude 键存在", tags is not None and "GPSLongitude" in tags)

        # --- 2) 坐标换算：度分秒 → 十进制 + 半球符号 ---
        print("\n[2] 坐标换算")
        gps = X.gps_to_decimal(tags)
        check("解析成功", gps is not None)
        if gps:
            check("纬度 ≈ 22.5431", abs(gps[0] - 22.5431) < 0.001, gps[0])
            check("经度 ≈ 114.0579", abs(gps[1] - 114.0579) < 0.001, gps[1])
        s_tags = dict(tags or {})
        s_tags["GPSLatitudeRef"] = "S"
        s_tags["GPSLongitudeRef"] = "W"
        g2 = X.gps_to_decimal(s_tags)
        check("南纬/西经为负", g2 is not None and g2[0] < 0 and g2[1] < 0, g2)
        check("无 GPS 返回 None", X.gps_to_decimal({"Model": "X"}) is None)

        # --- 3) 端到端 main(): geo 写入 / 无 key 不崩 / 幂等 / 不伤旧条目 ---
        print("\n[3] 端到端写 gallery.json")
        gallery = json.loads(bak)
        gallery.append({"title": "__gps_test__", "category": "new",
                        "thumb": "optimized/thumb/x.webp"})
        gallery_path.write_text(json.dumps(gallery, ensure_ascii=False),
                                encoding="utf-8")
        X.amap_key = lambda: ""  # 无 key: location 留空但不能崩
        X.main()
        out = {e["title"]: e for e in json.loads(gallery_path.read_text(encoding="utf-8"))}
        e = out.get("__gps_test__", {})
        check("geo 已写入", bool(e.get("geo")))
        if e.get("geo"):
            check("geo.lat 六位小数内正确", abs(e["geo"]["lat"] - 22.5431) < 0.001,
                  e["geo"]["lat"])
            check("geo.lng 正确", abs(e["geo"]["lng"] - 114.0579) < 0.001,
                  e["geo"]["lng"])
        check("exif 同步写入", e.get("exif", {}).get("camera") == "Panasonic S5II")
        check("旧条目 exif 未被破坏", out.get("bird01", {}).get("exif") is not None)
        before = e.get("geo")
        X.main()  # 重跑幂等
        e2 = {x["title"]: x for x in json.loads(
            gallery_path.read_text(encoding="utf-8"))}["__gps_test__"]
        check("重跑幂等", e2.get("geo") == before)

        # --- 4) 无 GPS 照片不覆盖手补 geo/location ---
        print("\n[4] 手补值保护")
        gallery = json.loads(bak)
        gallery[0]["geo"] = {"lat": 1.0, "lng": 2.0}
        gallery[0]["location"] = "手补地点"
        gallery_path.write_text(json.dumps(gallery, ensure_ascii=False),
                                encoding="utf-8")
        X.main()
        first = json.loads(gallery_path.read_text(encoding="utf-8"))[0]
        check("手补 geo 保留", first.get("geo") == {"lat": 1.0, "lng": 2.0})
        check("手补 location 保留", first.get("location") == "手补地点")
    finally:
        gallery_path.write_text(bak, encoding="utf-8")
        tmp_img.unlink(missing_ok=True)

    print(f"\n{'全部通过 ✅' if not failures else f'{len(failures)} 项失败 ❌'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
