# lio-photo-portfolio

纯静态摄影作品集：`index.html`（瀑布流画廊）+ `map.html`（机位地图，Leaflet + OpenStreetMap，纯前端无需 key）。

## 页面

- **作品集** `index.html` — 分类筛选、瀑布流、lightbox（拍摄参数 + 地点）
- **机位地图** `map.html` — 有坐标的照片标注在地图上，点标记看缩略图 + 拍摄信息；无坐标的照片不上地图

两页右上角有胶囊导航互相跳转。

## gallery.json 字段

每张照片一个条目。关键字段：

| 字段 | 说明 |
|------|------|
| `title` / `category` | 标题（文件名）/ 分类 |
| `thumb` / `display` / `full` | 400px / 1200px / 2560px WebP 路径 |
| `exif` | 拍摄参数对象（有 EXIF 才填） |
| `location` | 地点名字符串（可手补，如 `"深圳湾公园"`） |
| `geo` | 拍摄坐标对象（可手补，见下） |

### 手动补坐标（上地图）

给照片加 `geo` 字段即可出现在机位地图上：

```json
"geo": { "lat": 22.5431, "lng": 114.0579 }
```

- `lat` 纬度（-90~90）、`lng` 经度（-180~180），均为十进制度数
- 也接受 `{ "latitude", "longitude" }` 或 `[lat, lng]` 写法
- 原图 EXIF 带 GPS 时，`python3 extract_exif.py` 会自动写入 `geo`
- `python3 tools.py deploy --go` 与 `deploy.sh`（generate_gallery.py）重新生成时都不会覆盖手补的 `exif` / `location` / `geo`（按 title 合并保护）

## 本地预览

```bash
python3 -m http.server 8000
# http://localhost:8000/        作品集
# http://localhost:8000/map.html 机位地图
```

## 测试

```bash
node tests/dom_smoke_test.js       # 首页 lightbox 渲染冒烟
node tests/map_smoke_test.js       # 地图数据解析 / 标记 / 弹窗冒烟
python3 tests/extract_gps_test.py  # EXIF GPS→geo 链路回归（合成 GPS 图，无需联网）
```
