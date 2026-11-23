#!/usr/bin/env python3
"""
世界かんがい施設遺産（日本）CSV → RDF(Turtle) / GeoJSON 変換スクリプト

使い方:
  pip install rdflib
  python csv_to_rdf.py --csv ../data/whis_japan.csv \
      --base https://YOUR_GITHUB_NAME.github.io/whis-lod/ \
      --prefqid ../data/prefecture_qid.csv \
      --out-ttl ../data/whis_japan.ttl \
      --out-geojson ../viewer/whis_japan.geojson

方針:
- owl:sameAs（Wikidataとの同一関係）は verified=1 の行だけに付ける。
  （自動で候補を探しても、本人が確かめるまでは「同じもの」とは言わない）
- 座標がない行も RDF には出す。GeoJSON（地図用）には座標がある行だけ出す。
- 語彙は schema.org / GeoSPARQL / W3C Basic Geo / DCMI / DCAT を使い、
  足りない分だけ独自語彙 whis: を最小限で定義する。
"""
import argparse
import csv
import json
import sys
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef, BNode
from rdflib.namespace import RDF, RDFS, OWL, XSD, DCTERMS, DCAT

SCHEMA = Namespace("https://schema.org/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
WGS = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
WD = Namespace("http://www.wikidata.org/entity/")

# JIS X 0401 都道府県コード（ISO 3166-2:JP の数字部分と同じ）
PREF_CODE = {
    "北海道": "01", "青森県": "02", "岩手県": "03", "宮城県": "04", "秋田県": "05",
    "山形県": "06", "福島県": "07", "茨城県": "08", "栃木県": "09", "群馬県": "10",
    "埼玉県": "11", "千葉県": "12", "東京都": "13", "神奈川県": "14", "新潟県": "15",
    "富山県": "16", "石川県": "17", "福井県": "18", "山梨県": "19", "長野県": "20",
    "岐阜県": "21", "静岡県": "22", "愛知県": "23", "三重県": "24", "滋賀県": "25",
    "京都府": "26", "大阪府": "27", "兵庫県": "28", "奈良県": "29", "和歌山県": "30",
    "鳥取県": "31", "島根県": "32", "岡山県": "33", "広島県": "34", "山口県": "35",
    "徳島県": "36", "香川県": "37", "愛媛県": "38", "高知県": "39", "福岡県": "40",
    "佐賀県": "41", "長崎県": "42", "熊本県": "43", "大分県": "44", "宮崎県": "45",
    "鹿児島県": "46", "沖縄県": "47",
}

# 農水省資料の対象施設区分（ダム、ため池等、堰・分水施設、水路、排水施設、古い水車 など）
FACILITY_TYPES = {"ダム", "ため池", "堰", "分水施設", "水路", "排水施設", "水車", "揚水機場", "用水群", "その他"}


def load_pref_qids(path):
    """prefecture_qid.csv（列: prefecture,qid）を読む。なければ空。"""
    if not path or not Path(path).exists():
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("qid"):
                out[r["prefecture"]] = r["qid"].strip()
    return out


def parse_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def split_urls(s):
    """source_url は「 | 」区切りで複数可。"""
    return [u.strip() for u in (s or "").split("|") if u.strip()]


def validate(rows):
    """データの穴と矛盾を一覧にする（止めずに警告だけ出す）。"""
    problems = []
    ids = set()
    for r in rows:
        rid = r["id"]
        if rid in ids:
            problems.append(f"{rid}: id が重複しています")
        ids.add(rid)
        if r["prefecture"] not in PREF_CODE:
            problems.append(f"{rid}: 都道府県名が不正です（{r['prefecture']}）")
        lat, lon = parse_float(r.get("lat")), parse_float(r.get("lon"))
        if (lat is None) != (lon is None):
            problems.append(f"{rid}: lat と lon の片方だけが入っています")
        if lat is not None and not (20 <= lat <= 46 and 122 <= lon <= 154):
            problems.append(f"{rid}: 座標が日本の範囲外です（{lat},{lon}）")
        y = r.get("registered_year", "")
        if not (y.isdigit() and 2014 <= int(y) <= 2100):
            problems.append(f"{rid}: registered_year が不正です（{y}）")
        if r.get("verified") == "1" and not r.get("wikidata_qid"):
            problems.append(f"{rid}: verified=1 なのに wikidata_qid が空です")
        by = r.get("built_year", "")
        if by and not by.isdigit():
            problems.append(f"{rid}: built_year は西暦の整数で（{by}）")
        elif by and y.isdigit() and int(y) - int(by) < 100:
            problems.append(f"{rid}: 登録基準（建設から100年以上）と矛盾します（built {by} / registered {y}）")
        if by and not r.get("built_year_basis"):
            problems.append(f"{rid}: built_year の根拠（built_year_basis）が空です")
        ft = r.get("facility_type", "")
        if ft and ft not in FACILITY_TYPES:
            problems.append(f"{rid}: facility_type『{ft}』は語彙にありません（{sorted(FACILITY_TYPES)}）")
    return problems


def build_graph(rows, base, pref_qids, dataset_meta):
    base = base.rstrip("/") + "/"
    RES = Namespace(base + "resource/")
    WHIS = Namespace(base + "ontology#")

    g = Graph()
    for p, ns in [("schema", SCHEMA), ("geo", GEO), ("wgs84", WGS), ("wd", WD), ("whis", WHIS),
                  ("res", RES), ("dcterms", DCTERMS), ("dcat", DCAT), ("owl", OWL)]:
        g.bind(p, ns)

    # --- 最小限の独自語彙 ---
    g.add((WHIS.HeritageIrrigationStructure, RDF.type, OWL.Class))
    g.add((WHIS.HeritageIrrigationStructure, RDFS.subClassOf, SCHEMA.LandmarksOrHistoricalBuildings))
    g.add((WHIS.HeritageIrrigationStructure, RDFS.label, Literal("世界かんがい施設遺産", lang="ja")))
    g.add((WHIS.HeritageIrrigationStructure, RDFS.label, Literal("World Heritage Irrigation Structure", lang="en")))
    for prop, ja, en, rng in [
        (WHIS.registeredYear, "登録年", "year of registration", XSD.gYear),
        (WHIS.builtYear, "建設年（着工・完成のどちらかは note に記載）", "year built", XSD.gYear),
        (WHIS.facilityType, "施設の種類", "facility type", XSD.string),
        (WHIS.waterSource, "水源の川", "water source (river)", None),
        (WHIS.prefectureCode, "都道府県コード（ISO 3166-2:JP）", "prefecture code", XSD.string),
        (WHIS.irrigatedArea, "かんがい面積（ha）", "irrigated area (ha)", XSD.decimal),
        (WHIS.managedBy, "管理者", "managing organization", XSD.string),
        (WHIS.builtYearBasis, "建設年の根拠（着工・完成・供用開始など）", "basis of built year", XSD.string),
        (WHIS.representativePoint, "代表地点（座標を取る場所の名前）", "representative point name", XSD.string),
    ]:
        g.add((prop, RDF.type, RDF.Property))
        g.add((prop, RDFS.label, Literal(ja, lang="ja")))
        g.add((prop, RDFS.label, Literal(en, lang="en")))
        if rng is not None:
            g.add((prop, RDFS.range, rng))

    # --- データセットのメタデータ（LODチャレンジの審査観点「開放性」「持続可能性」向け） ---
    ds = URIRef(base + "dataset")
    g.add((ds, RDF.type, DCAT.Dataset))
    g.add((ds, DCTERMS.title, Literal(dataset_meta["title_ja"], lang="ja")))
    g.add((ds, DCTERMS.title, Literal(dataset_meta["title_en"], lang="en")))
    g.add((ds, DCTERMS.license, URIRef(dataset_meta["license"])))
    g.add((ds, DCTERMS.creator, Literal(dataset_meta["creator"])))
    g.add((ds, DCTERMS.modified, Literal(dataset_meta["modified"], datatype=XSD.date)))
    for s in dataset_meta["sources"]:
        g.add((ds, DCTERMS.source, URIRef(s)))

    for r in rows:
        s = RES[r["id"]]
        g.add((s, RDF.type, WHIS.HeritageIrrigationStructure))
        g.add((s, DCTERMS.identifier, Literal(r["id"])))
        g.add((s, SCHEMA.name, Literal(r["name_ja"], lang="ja")))
        g.add((s, RDFS.label, Literal(r["name_ja"], lang="ja")))
        if r.get("name_en"):
            g.add((s, SCHEMA.name, Literal(r["name_en"], lang="en")))
            g.add((s, RDFS.label, Literal(r["name_en"], lang="en")))
        g.add((s, DCTERMS.isPartOf, ds))

        # 所在地
        pref = r["prefecture"]
        g.add((s, SCHEMA.addressRegion, Literal(pref, lang="ja")))
        if pref in PREF_CODE:
            g.add((s, WHIS.prefectureCode, Literal("JP-" + PREF_CODE[pref])))
        if pref in pref_qids:
            g.add((s, SCHEMA.containedInPlace, WD[pref_qids[pref]]))
        if r.get("municipality"):
            g.add((s, SCHEMA.addressLocality, Literal(r["municipality"], lang="ja")))

        # 年
        if r.get("registered_year"):
            g.add((s, WHIS.registeredYear, Literal(r["registered_year"], datatype=XSD.gYear)))
        if r.get("built_year"):
            g.add((s, WHIS.builtYear, Literal(r["built_year"].zfill(4), datatype=XSD.gYear)))
        if r.get("built_year_basis"):
            g.add((s, WHIS.builtYearBasis, Literal(r["built_year_basis"], lang="ja")))
        if r.get("representative_point"):
            g.add((s, WHIS.representativePoint, Literal(r["representative_point"], lang="ja")))

        # 種類・水源・管理者・面積
        if r.get("facility_type"):
            g.add((s, WHIS.facilityType, Literal(r["facility_type"], lang="ja")))
        if r.get("water_source_river_qid"):
            g.add((s, WHIS.waterSource, WD[r["water_source_river_qid"]]))
        elif r.get("water_source_river"):
            g.add((s, WHIS.waterSource, Literal(r["water_source_river"], lang="ja")))
        if r.get("managing_org"):
            g.add((s, WHIS.managedBy, Literal(r["managing_org"], lang="ja")))
        area = parse_float(r.get("irrigated_area_ha"))
        if area is not None:
            g.add((s, WHIS.irrigatedArea, Literal(str(area), datatype=XSD.decimal)))

        # 座標（GeoSPARQL と W3C Basic Geo の両方。使う側のツールを選ばないように）
        lat, lon = parse_float(r.get("lat")), parse_float(r.get("lon"))
        if lat is not None and lon is not None:
            g.add((s, WGS.lat, Literal(str(lat), datatype=XSD.decimal)))
            g.add((s, WGS.long, Literal(str(lon), datatype=XSD.decimal)))
            geom = URIRef(str(s) + "/geometry")
            g.add((s, GEO.hasGeometry, geom))
            g.add((geom, RDF.type, GEO.Geometry))
            g.add((geom, GEO.asWKT, Literal(f"POINT({lon} {lat})", datatype=GEO.wktLiteral)))

        # 外部リンク
        if r.get("verified") == "1" and r.get("wikidata_qid"):
            g.add((s, OWL.sameAs, WD[r["wikidata_qid"]]))
        if r.get("icid_page_url"):
            g.add((s, RDFS.seeAlso, URIRef(r["icid_page_url"])))
        for u in split_urls(r.get("source_url")):
            g.add((s, DCTERMS.source, URIRef(u)))
        if r.get("note"):
            g.add((s, RDFS.comment, Literal(r["note"], lang="ja")))
    return g


def build_geojson(rows):
    feats = []
    for r in rows:
        lat, lon = parse_float(r.get("lat")), parse_float(r.get("lon"))
        if lat is None or lon is None:
            continue
        props = {k: r.get(k, "") for k in
                 ["id", "name_ja", "name_en", "prefecture", "municipality", "registered_year",
                  "built_year", "built_year_basis", "facility_type", "water_source_river", "managing_org",
                  "irrigated_area_ha", "representative_point", "wikidata_qid", "verified", "source_url", "note"]}
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                      "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--base", required=True, help="公開先のURL（例: https://yourname.github.io/whis-lod/）")
    ap.add_argument("--prefqid", default=None)
    ap.add_argument("--out-ttl", required=True)
    ap.add_argument("--out-geojson", required=True)
    ap.add_argument("--creator", default="【氏名またはハンドルネーム】")
    ap.add_argument("--modified", default="2026-12-31")
    a = ap.parse_args(argv)

    with open(a.csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    problems = validate(rows)
    n_coord = sum(1 for r in rows if parse_float(r.get("lat")) is not None)
    n_ver = sum(1 for r in rows if r.get("verified") == "1")
    print(f"行数: {len(rows)} / 座標あり: {n_coord} / Wikidata確認済み: {n_ver}")
    for p in problems:
        print("警告:", p, file=sys.stderr)

    meta = {
        "title_ja": "世界かんがい施設遺産（日本）Linked Open Data",
        "title_en": "World Heritage Irrigation Structures in Japan as Linked Open Data",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "creator": a.creator,
        "modified": a.modified,
        "sources": sorted({u for r in rows for u in split_urls(r.get("source_url"))}),
    }
    g = build_graph(rows, a.base, load_pref_qids(a.prefqid), meta)
    Path(a.out_ttl).parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=a.out_ttl, format="turtle")
    Path(a.out_geojson).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out_geojson, "w", encoding="utf-8") as f:
        json.dump(build_geojson(rows), f, ensure_ascii=False, indent=1)
    print(f"トリプル数: {len(g)} → {a.out_ttl}")
    print(f"GeoJSON → {a.out_geojson}")
    return 0 if not any("重複" in p or "不正" in p for p in problems) else 1


if __name__ == "__main__":
    sys.exit(main())
