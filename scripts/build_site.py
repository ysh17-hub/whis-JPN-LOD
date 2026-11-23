#!/usr/bin/env python3
"""
公開用サイト（GitHub Pages の docs/ フォルダ）を一式つくるスクリプト。

  python build_site.py --base https://【ユーザー名】.github.io/whis-lod/ --creator "【氏名またはハンドルネーム】"

つくるもの（すべて docs/ の中）:
  whis_japan.ttl / whis_japan.jsonld / whis_japan.geojson / whis_japan.csv  … データ本体
  resource/WHIS-JP-001.html …                                             … 施設ごとのページ（URIを開くと読める）
  ontology.html                                                           … 独自語彙 whis: の説明
  index.html（地図）はリポジトリにあるものをそのまま使う

GitHub Pages は「/resource/WHIS-JP-001」へのアクセスに「resource/WHIS-JP-001.html」を返すので、
RDF の中の URI（https://…/resource/WHIS-JP-001）をブラウザで開くと、その施設のページが表示される。
各ページには schema.org の JSON-LD を埋め込み、検索エンジンや他のプログラムも読めるようにしている。
"""
import argparse
import csv
import html
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import csv_to_rdf as conv  # noqa: E402

ONTOLOGY_TERMS = [
    ("HeritageIrrigationStructure", "クラス", "世界かんがい施設遺産に登録された施設。schema:LandmarksOrHistoricalBuildings のサブクラス。"),
    ("registeredYear", "xsd:gYear", "ICID（国際かんがい排水委員会）による登録年。"),
    ("builtYear", "xsd:gYear", "建設年。着工・完成・供用開始のどれかは builtYearBasis に書く。"),
    ("builtYearBasis", "文字列", "builtYear の根拠（着工・完成・供用開始・資料記載年など）。"),
    ("facilityType", "文字列", "施設の種類（水路・ため池・堰・用水群・揚水機場など）。農水省の対象施設区分に合わせた。"),
    ("waterSource", "文字列またはWikidata", "水源の川・湖など。Wikidata の QID が分かるときは IRI で示す。"),
    ("prefectureCode", "文字列", "都道府県コード（ISO 3166-2:JP 形式、例: JP-04）。"),
    ("irrigatedArea", "xsd:decimal", "かんがい面積（ha）。資料によって値が異なるものは空欄にし、comment に両方を書いた。"),
    ("managedBy", "文字列", "管理者（土地改良区など）。"),
    ("representativePoint", "文字列", "座標を取った代表地点の名前（取水口・堰・池など）。"),
]

FIELD_LABELS = [
    ("name_en", "英語名"), ("prefecture", "都道府県"), ("municipality", "市町村"),
    ("registered_year", "登録年"), ("built_year", "建設年"), ("built_year_basis", "建設年の根拠"),
    ("facility_type", "種類"), ("water_source_river", "水源"), ("managing_org", "管理者"),
    ("irrigated_area_ha", "かんがい面積（ha）"), ("representative_point", "代表地点"),
    ("lat", "緯度"), ("lon", "経度"), ("note", "注記"),
]


def jsonld_for(r, base):
    """施設ページに埋め込む schema.org の JSON-LD。"""
    uri = base + "resource/" + r["id"]
    d = {
        "@context": "https://schema.org",
        "@type": "LandmarksOrHistoricalBuildings",
        "@id": uri,
        "identifier": r["id"],
        "name": [{"@value": r["name_ja"], "@language": "ja"}] +
                ([{"@value": r["name_en"], "@language": "en"}] if r.get("name_en") else []),
        "address": {"@type": "PostalAddress", "addressCountry": "JP",
                    "addressRegion": r["prefecture"], "addressLocality": r.get("municipality", "")},
        "isPartOf": base + "dataset",
        "citation": conv.split_urls(r.get("source_url")),
    }
    lat, lon = conv.parse_float(r.get("lat")), conv.parse_float(r.get("lon"))
    if lat is not None and lon is not None:
        d["geo"] = {"@type": "GeoCoordinates", "latitude": lat, "longitude": lon}
    if r.get("verified") == "1" and r.get("wikidata_qid"):
        d["sameAs"] = "http://www.wikidata.org/entity/" + r["wikidata_qid"]
    return d


PAGE_CSS = """body{font-family:system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;max-width:820px;margin:24px auto;padding:0 16px;line-height:1.6}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #eee;padding:6px;text-align:left;vertical-align:top}
th{width:11em;color:#444}code{background:#f4f4f4;padding:1px 4px}nav a{margin-right:12px}small{color:#666}"""


def resource_page(r, base, creator):
    e = html.escape
    rows = "".join(f"<tr><th>{e(lbl)}</th><td>{e(r.get(k, '') or '—')}</td></tr>" for k, lbl in FIELD_LABELS)
    wd = (f'<a href="https://www.wikidata.org/wiki/{e(r["wikidata_qid"])}">{e(r["wikidata_qid"])}</a>（確認済み）'
          if r.get("verified") == "1" and r.get("wikidata_qid") else "—")
    srcs = "".join(f'<li><a href="{e(u)}">{e(u)}</a></li>' for u in conv.split_urls(r.get("source_url")))
    ld = json.dumps(jsonld_for(r, base), ensure_ascii=False, indent=1).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(r['name_ja'])}｜世界かんがい施設遺産（日本）LOD</title>
<link rel="alternate" type="text/turtle" href="../whis_japan.ttl">
<style>{PAGE_CSS}</style>
<script type="application/ld+json">
{ld}
</script></head><body>
<nav><a href="../index.html">地図</a><a href="../ontology.html">語彙</a><a href="../whis_japan.ttl">Turtle</a><a href="../whis_japan.jsonld">JSON-LD</a><a href="../whis_japan.csv">CSV</a></nav>
<h1>{e(r['name_ja'])}</h1>
<p><small>URI: <code>{e(base + 'resource/' + r['id'])}</code></small></p>
<table>{rows}<tr><th>Wikidata</th><td>{wd}</td></tr></table>
<h2>出典</h2><ul>{srcs}</ul>
<p><small>データ: CC BY 4.0（作成: {e(creator)}）。数値は出典に書かれた範囲のみを記載し、資料で値が異なるものは空欄にして注記に両方を書いています。</small></p>
</body></html>
"""


def ontology_page(base):
    e = html.escape
    rows = "".join(f'<tr id="{e(t)}"><th><code>whis:{e(t)}</code></th><td>{e(k)}</td><td>{e(d)}</td></tr>'
                   for t, k, d in ONTOLOGY_TERMS)
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>語彙 whis:｜世界かんがい施設遺産（日本）LOD</title><style>{PAGE_CSS}</style></head><body>
<nav><a href="index.html">地図</a><a href="whis_japan.ttl">Turtle</a></nav>
<h1>独自語彙 whis:</h1>
<p>名前空間: <code>{e(base)}ontology#</code><br>
既存の語彙（schema.org、GeoSPARQL、W3C Basic Geo、DCMI Terms、DCAT、OWL）で表せない項目だけを定義しています。</p>
<table><tr><th>用語</th><td><b>値</b></td><td><b>説明</b></td></tr>{rows}</table>
</body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--creator", default="【氏名またはハンドルネーム】")
    ap.add_argument("--modified", default="2026-12-31")
    ap.add_argument("--csv", default=str(ROOT / "data" / "whis_japan.csv"))
    ap.add_argument("--prefqid", default=str(ROOT / "data" / "prefecture_qid.csv"))
    ap.add_argument("--docs", default=str(ROOT / "docs"))
    a = ap.parse_args(argv)
    base = a.base.rstrip("/") + "/"
    docs = Path(a.docs)
    (docs / "resource").mkdir(parents=True, exist_ok=True)

    rc = conv.main(["--csv", a.csv, "--base", base, "--prefqid", a.prefqid,
                    "--out-ttl", str(docs / "whis_japan.ttl"), "--out-geojson", str(docs / "whis_japan.geojson"),
                    "--creator", a.creator, "--modified", a.modified])
    from rdflib import Graph
    g = Graph().parse(docs / "whis_japan.ttl", format="turtle")
    (docs / "whis_japan.jsonld").write_text(g.serialize(format="json-ld", indent=1), encoding="utf-8")
    shutil.copyfile(a.csv, docs / "whis_japan.csv")

    with open(a.csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        (docs / "resource" / f"{r['id']}.html").write_text(resource_page(r, base, a.creator), encoding="utf-8")
    (docs / "ontology.html").write_text(ontology_page(base), encoding="utf-8")
    print(f"施設ページ {len(rows)} 件、ontology.html、JSON-LD、CSV を {docs} に出力しました")
    return rc


if __name__ == "__main__":
    sys.exit(main())
