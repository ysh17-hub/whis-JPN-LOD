#!/usr/bin/env python3
"""
リンクの健康診断：出典URL・外部データベースへのリンク・写真のURLが今も開けるかを確かめ、
docs/link_report.csv に書く（検証レポート quality.html に結果が出る）。

GitHub Actions で毎月動かす想定（.github/workflows/linkcheck.yml）。標準ライブラリだけで動く。
使い方:  python scripts/check_links.py
"""
import csv
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = "whis-lod link checker (https://github.com/ysh17-hub/whis-lod)"


def collect():
    """確かめるURLを (種類, URL, 施設ID) で集める。"""
    out = []
    with open(ROOT / "data" / "whis_japan.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            for u in (r.get("source_url") or "").split("|"):
                if u.strip():
                    out.append(("出典", u.strip(), r["id"]))
    for name, col, kind in [("external_links.csv", "url", "外部リンク"), ("images.csv", "file_page", "写真"),
                            ("address_links.csv", "loa_uri", "住所LOD")]:
        p = ROOT / "data" / name
        if p.exists():
            with open(p, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if r.get(col):
                        out.append((kind, r[col], r["id"]))
    dead = set()
    sp = ROOT / "data" / "source_status.csv"
    if sp.exists():
        with open(sp, encoding="utf-8-sig") as f:
            dead = {r["url"] for r in csv.DictReader(f) if r.get("status") == "消失"}
    out = [(k, u, i) for k, u, i in out if u not in dead]   # 消えたと分かっている出典は数えない（ページに「リンク切れ」と表示済み）
    seen, uniq = set(), []
    for k, u, i in out:
        if u not in seen:
            seen.add(u)
            uniq.append((k, u, i))
    return uniq


def check(url, opener=urllib.request.urlopen, timeout=20):
    """HEAD で確かめ、HEAD を受け付けないサーバーには GET で確かめる。(状態コード, メモ) を返す。"""
    from urllib.parse import quote, urlsplit, urlunsplit
    parts = urlsplit(url)
    safe = urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%()_-.~!$&'*+,;=:@"),
                       parts.query, parts.fragment))
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(safe, method=method, headers={"User-Agent": UA})
        try:
            with opener(req, timeout=timeout) as r:
                return r.status, ""
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 501):
                continue
            return e.code, ""
        except Exception as e:  # タイムアウト・名前解決の失敗など
            if method == "HEAD":
                continue
            return 0, type(e).__name__
    return 0, "unknown"


def main(opener=urllib.request.urlopen, sleep=0.5):
    rows = []
    for kind, url, fid in collect():
        status, note = check(url, opener)
        rows.append({"kind": kind, "url": url, "id": fid, "status": status, "ok": "1" if 200 <= status < 400 else "0",
                     "note": note, "checked": date.today().isoformat()})
        time.sleep(sleep)
    out = ROOT / "docs" / "link_report.csv"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["kind", "url", "id", "status", "ok", "note", "checked"])
        w.writeheader()
        w.writerows(rows)
    bad = [r for r in rows if r["ok"] != "1"]
    print(f"リンク {len(rows)} 件を確認：開けた {len(rows) - len(bad)} 件、開けなかった {len(bad)} 件 → {out}")
    for r in bad:
        print(f"  {r['status']} {r['kind']} {r['id']} {r['url']} {r['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
