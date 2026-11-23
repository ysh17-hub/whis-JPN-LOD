#!/usr/bin/env python3
"""
代表地点の標高と、昔の空中写真があるかを、国土地理院の地理院タイルから求めて data/point_terrain.csv に書く。

- 標高：PNG形式の標高タイル。細かいものから順に DEM1A（1m）→ DEM5A → DEM5B → DEM5C（5m）→ DEM10B（10m）。
  計算式は国土地理院「標高タイルの詳細仕様」https://maps.gsi.go.jp/development/demtile.html
  x = 2^16 R + 2^8 G + B、x < 2^23 なら h = x × 0.01m、x = 2^23 は無効値、x > 2^23 なら h = (x − 2^24) × 0.01m
- 昔の空中写真：1945〜1950年（ort_USA10）・1961〜1969年（ort_old10）・1974〜1978年（gazo1）の
  ズーム16のタイルがあり、その地点の画素が透明でないか。
- 外部のライブラリは使わない（PNG は標準ライブラリの zlib で読む）ので、GitHub Actions でもそのまま動く。
- まだ値のない施設と、座標が変わった施設だけを計算する（--all ですべて計算し直す）。

使い方:  python scripts/terrain.py            （lod.py build からも自動で呼ばれる）
"""
import argparse
import csv
import math
import struct
import sys
import urllib.request
import zlib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TILE = "https://cyberjapandata.gsi.go.jp/xyz/{id}/{z}/{x}/{y}.{ext}"
DEMS = [("DEM1A", "dem1a_png", 17), ("DEM5A", "dem5a_png", 15), ("DEM5B", "dem5b_png", 15),
        ("DEM5C", "dem5c_png", 15), ("DEM10B", "dem_png", 14)]
AERIAL = [("aerial_1945_1950", "ort_USA10", "png"), ("aerial_1961_1969", "ort_old10", "png"),
          ("aerial_1974_1978", "gazo1", "jpg"), ("aerial_latest", "seamlessphoto", "jpg")]
FIELDS = ["id", "lat", "lon", "elevation_m", "elevation_dem", "aerial_1945_1950", "aerial_1961_1969",
          "aerial_1974_1978", "aerial_latest", "gsi_elevation_api_m", "gsi_elevation_api_mesh", "retrieved"]


def tile_xy(lat, lon, z):
    """緯度経度 → タイル番号とタイル内の画素（Webメルカトル）。"""
    n = 2 ** z
    xf = (lon + 180) / 360 * n
    r = math.radians(lat)
    yf = (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n
    x, y = int(xf), int(yf)
    return x, y, int((xf - x) * 256), int((yf - y) * 256)


def png_pixel(data, px, py):
    """PNG（8ビット、RGB・RGBA・パレット・グレー）の1画素を (R, G, B, A) で返す。"""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG ではありません")
    pos, idat, plte, trns = 8, b"", None, None
    while pos < len(data):
        ln, = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif typ == b"PLTE":
            plte = body
        elif typ == b"tRNS":
            trns = body
        elif typ == b"IDAT":
            idat += body
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if depth != 8 or interlace:
        raise ValueError("8ビット・インターレースなしの PNG だけ読めます")
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = w * bpp
    prev = bytearray(stride)
    row = None
    for yy in range(py + 1):          # 必要な行まで、フィルタを元に戻しながら読む
        f = raw[yy * (stride + 1)]
        cur = bytearray(raw[yy * (stride + 1) + 1:(yy + 1) * (stride + 1)])
        for i in range(stride):
            a = cur[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                cur[i] = (cur[i] + a) & 255
            elif f == 2:
                cur[i] = (cur[i] + b) & 255
            elif f == 3:
                cur[i] = (cur[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                cur[i] = (cur[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev, row = cur, cur
    v = row[px * bpp:(px + 1) * bpp]
    if ctype == 2:
        return v[0], v[1], v[2], 255
    if ctype == 6:
        return v[0], v[1], v[2], v[3]
    if ctype == 3:
        i = v[0]
        alpha = trns[i] if trns and i < len(trns) else 255
        return plte[3 * i], plte[3 * i + 1], plte[3 * i + 2], alpha
    if ctype == 0:
        return v[0], v[0], v[0], 255
    return v[0], v[0], v[0], v[1]


def fetch(url, timeout=20):
    """タイルを取ってくる。ない（404）ときは None。"""
    req = urllib.request.Request(url, headers={"User-Agent": "whis-lod (https://github.com/ysh17-hub/whis-lod)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def elevation(lat, lon, get=fetch):
    for name, tid, z in DEMS:
        x, y, px, py = tile_xy(lat, lon, z)
        data = get(TILE.format(id=tid, z=z, x=x, y=y, ext="png"))
        if not data:
            continue
        r, g, b, _ = png_pixel(data, px, py)
        v = r * 65536 + g * 256 + b
        if v == 2 ** 23:              # 無効値（その地点にこのメッシュの値がない）
            continue
        h = v * 0.01 if v < 2 ** 23 else (v - 2 ** 24) * 0.01
        return round(h, 2), name
    return None, ""


def aerial(lat, lon, tid, ext, get=fetch):
    z = 18 if tid == "seamlessphoto" else 16
    x, y, px, py = tile_xy(lat, lon, z)
    data = get(TILE.format(id=tid, z=z, x=x, y=y, ext=ext))
    if not data:
        return "0"
    if ext == "png":
        return "1" if png_pixel(data, px, py)[3] > 0 else "0"   # 透明（写真の範囲外）なら無し
    return "1"


def update(csv_path, out_path, recompute_all=False, get=fetch, log=print):
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    old = {}
    if Path(out_path).exists():
        with open(out_path, encoding="utf-8-sig") as f:
            old = {r["id"]: r for r in csv.DictReader(f)}
    out, n_new = [], 0
    for r in rows:
        if not (r.get("lat") and r.get("lon")):
            continue
        lat, lon = float(r["lat"]), float(r["lon"])
        prev = old.get(r["id"])
        same_point = prev and prev.get("lat") and abs(float(prev["lat"]) - lat) < 1e-7 and abs(float(prev["lon"]) - lon) < 1e-7
        if prev and same_point and not recompute_all:
            out.append({k: prev.get(k, "") for k in FIELDS})
            continue
        h, dem = elevation(lat, lon, get)
        rec = {"id": r["id"], "lat": r["lat"], "lon": r["lon"],
               "elevation_m": "" if h is None else f"{h:.1f}", "elevation_dem": dem,
               "gsi_elevation_api_m": "", "gsi_elevation_api_mesh": "", "retrieved": date.today().isoformat()}
        for col, tid, ext in AERIAL:
            rec[col] = aerial(lat, lon, tid, ext, get)
        out.append(rec)
        n_new += 1
        log(f"  {r['id']} {r['name_ja']}：標高 {rec['elevation_m'] or '—'}m（{dem or 'なし'}）")
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    return n_new


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(ROOT / "data" / "whis_japan.csv"))
    ap.add_argument("--out", default=str(ROOT / "data" / "point_terrain.csv"))
    ap.add_argument("--all", action="store_true", help="すべての施設を計算し直す")
    a = ap.parse_args(argv)
    n = update(a.csv, a.out, a.all)
    print(f"標高・空中写真：{n} 施設を計算しました → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
