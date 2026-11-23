#!/usr/bin/env python3
"""
Wikidata から「候補」を取ってくるスクリプト（自分のパソコンで実行してください）

1) 都道府県の Wikidata ID（QID）を、ISO 3166-2 コード（Wikidata の P300）で取得
   → ../data/prefecture_qid.csv
2) 各施設の名前で Wikidata を検索し、候補（QID・説明・座標 P625）を一覧にする
   → ../data/wikidata_candidates.csv

重要:
- 2) は「候補」です。同名の別物（同じ名前の川・池など）が混ざります。
  候補を自分で開いて確かめ、正しいものだけ whis_japan.csv の wikidata_qid に書き、verified を 1 にしてください。
- Wikidata に施設が無い場合は、それ自体がこのデータセットの価値（＝これまでつながっていなかった）になります。
  件数を数えて、作品説明に書けます。
- Wikidata への問い合わせは、間隔をあけて行います（相手のサーバーに負担をかけないため）。

使い方（ふつうはリポジトリ直下の lod.py から呼ぶ）:
  python lod.py wikidata
直接呼ぶ場合:
  python scripts/fetch_wikidata.py --csv data/whis_japan.csv --outdir data --contact https://github.com/【ユーザー名】/whis-lod
"""
import argparse
import csv
import time
from pathlib import Path

import requests

UA_TMPL = "whis-lod/1.0 ({contact}) python-requests"   # Wikimedia の User-Agent 方針：連絡先（URLかメール）を入れる
SPARQL = "https://query.wikidata.org/sparql"
API = "https://www.wikidata.org/w/api.php"


def get_json(session, url, params, tries=5):
    """一時的なエラー（混雑・429・5xx・通信切れ）のときは、間隔をあけてやり直す。"""
    wait = 5
    for i in range(tries):
        try:
            r = session.get(url, params=params, timeout=60)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if i == tries - 1:
                raise
            print(f"  …一時的なエラー（{e}）。{wait}秒待ってやり直します")
            time.sleep(wait)
            wait *= 2


def get_prefecture_qids(session):
    q = """
    SELECT ?pref ?code ?label WHERE {
      ?pref wdt:P300 ?code .
      FILTER(STRSTARTS(?code, "JP-"))
      ?pref rdfs:label ?label . FILTER(LANG(?label) = "ja")
    }"""
    out = []
    for b in get_json(session, SPARQL, {"query": q, "format": "json"})["results"]["bindings"]:
        qid = b["pref"]["value"].rsplit("/", 1)[-1]
        out.append({"prefecture": b["label"]["value"], "code": b["code"]["value"], "qid": qid})
    return out


def search_entities(session, name, limit=5):
    return get_json(session, API, {"action": "wbsearchentities", "search": name, "language": "ja",
                                   "uselang": "ja", "type": "item", "limit": limit, "format": "json"}).get("search", [])


def get_coords(session, qids):
    if not qids:
        return {}
    values = " ".join(f"wd:{q}" for q in qids)
    q = f"""
    SELECT ?item ?coord WHERE {{
      VALUES ?item {{ {values} }}
      OPTIONAL {{ ?item wdt:P625 ?coord . }}
    }}"""
    out = {}
    for b in get_json(session, SPARQL, {"query": q, "format": "json"})["results"]["bindings"]:
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        if "coord" in b:
            # "Point(lon lat)"
            lon, lat = b["coord"]["value"].replace("Point(", "").replace(")", "").split()
            out[qid] = (float(lat), float(lon))
    return out


def split_names(name):
    """「山田堰、堀川用水、水車群」のような複合名は、全体と各部分の両方で検索する。"""
    parts = [name]
    for sep in ["、", "・"]:
        if sep in name:
            parts += [p for p in name.split(sep) if p]
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--contact", required=True, help="User-Agent に入れる連絡先（GitHubのリポジトリURLなど）")
    a = ap.parse_args(argv)
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers["User-Agent"] = UA_TMPL.format(contact=a.contact)

    prefs = get_prefecture_qids(s)
    with open(outdir / "prefecture_qid.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["prefecture", "code", "qid"])
        w.writeheader()
        w.writerows(sorted(prefs, key=lambda x: x["code"]))
    print(f"都道府県 {len(prefs)} 件 → prefecture_qid.csv")

    with open(a.csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    cands = []
    for r in rows:
        terms = split_names(r["name_ja"])
        rp = (r.get("representative_point") or "").split("（")[0].strip()
        if rp and rp not in terms:
            terms.append(rp)  # 例: 通潤橋、満濃池、山田堰 など「代表地点」の名前でも探す
        for term in terms:
            hits = search_entities(s, term)
            time.sleep(a.sleep)
            coords = get_coords(s, [h["id"] for h in hits])
            time.sleep(a.sleep)
            for rank, h in enumerate(hits, 1):
                lat, lon = coords.get(h["id"], (None, None))
                cands.append({
                    "id": r["id"], "name_ja": r["name_ja"], "prefecture": r["prefecture"],
                    "search_term": term, "rank": rank, "qid": h["id"],
                    "label": h.get("label", ""), "description": h.get("description", ""),
                    "lat": lat if lat is not None else "", "lon": lon if lon is not None else "",
                    "url": f"https://www.wikidata.org/wiki/{h['id']}",
                })
        print(f'{r["id"]} {r["name_ja"]}：候補 {sum(1 for c in cands if c["id"] == r["id"])} 件', flush=True)

    with open(outdir / "wikidata_candidates.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cands[0].keys()) if cands else ["id"])
        w.writeheader()
        w.writerows(cands)
    no_hit = [r["id"] for r in rows if not any(c["id"] == r["id"] for c in cands)]
    print(f"候補 {len(cands)} 行 → wikidata_candidates.csv")
    print(f"検索で候補が0件だった施設: {len(no_hit)} 件（候補があっても別物のことがあるので、最終的な「該当なし」は座標入力ツールで確認して決める）")


if __name__ == "__main__":
    main()
