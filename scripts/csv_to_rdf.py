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
- 遺産の一部分（構成施設）だけが Wikidata にある場合は wikidata_related に QID を書き（複数は ; 区切り）、
  schema:hasPart で結ぶ（同一ではないので sameAs にはしない）。
- 水源の川・湖が Wikidata にあるときは water_source_river_qid に QID を書き（複数は ; 区切り）、
  whis:waterSource で Wikidata の IRI に結ぶ。名前は whis:waterSourceName に必ず残す。
  （自動で候補を探しても、本人が確かめるまでは「同じもの」とは言わない）
- 座標がない行も RDF には出す。GeoJSON（地図用）には座標がある行だけ出す。
- 語彙は schema.org / GeoSPARQL / W3C Basic Geo / DCMI / DCAT を使い、
  足りない分だけ独自語彙 whis: を最小限で定義する。
"""
import argparse
import os
import re
import csv
import json
import sys
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef, BNode
from rdflib.namespace import RDF, RDFS, OWL, XSD, DCTERMS, DCAT, SKOS

SCHEMA = Namespace("https://schema.org/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
WGS = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
WD = Namespace("http://www.wikidata.org/entity/")
AGROVOC = Namespace("http://aims.fao.org/aos/agrovoc/")

# 施設の種類（SKOS の概念）。国際的な語彙とのつながり：
#  - AGROVOC（国連食糧農業機関 FAO の多言語シソーラス）
#  - Wikidata のクラス
# どの概念に当たるかは 2026-11-23 に AGROVOC の検索API・Wikidata の項目（ラベル・説明・上位クラス）を見て作成者が判断した。
# 意味の範囲が完全には同じと言えないものは closeMatch、相手の方が広いものは broadMatch にしている。
FACILITY_TYPE_CONCEPTS = {
    # 種類: (IRIの末尾, 英語名, 説明, [(関係, 相手のIRI), ...])
    "水路": ("canal", "irrigation canal",
             "水源から田畑へ水を運ぶ水路（トンネル・水路橋などを含む）。",
             [("closeMatch", AGROVOC["c_25340"]), ("exactMatch", WD["Q2935978"])]),
    "用水群": ("irrigation-system", "irrigation system",
               "取水施設・水路・ため池などがまとまって一つの用水の仕組みになっているもの。",
               [("closeMatch", AGROVOC["c_25332"]), ("closeMatch", WD["Q6129871"])]),
    "ため池": ("tameike", "irrigation reservoir (tameike)",
               "主に農業用水のために水をためる人工の池。",
               [("broadMatch", AGROVOC["c_8324"]), ("exactMatch", WD["Q112083751"])]),
    "堰": ("weir", "weir",
           "川をせき止めて水位を上げ、用水路へ水を取り入れる施設。",
           [("closeMatch", AGROVOC["c_8352"]), ("exactMatch", WD["Q1066997"])]),
    "揚水機場": ("pumping-station", "pumping station",
                 "ポンプで水をくみ上げて用水路へ送る施設。",
                 [("closeMatch", AGROVOC["c_535a6d71"]), ("closeMatch", WD["Q446013"])]),
}

# 標高を求めた標高タイル（地理院タイル）
DEM_TILES = {
    "DEM1A": "https://cyberjapandata.gsi.go.jp/xyz/dem1a_png/{z}/{x}/{y}.png",
    "DEM5A": "https://cyberjapandata.gsi.go.jp/xyz/dem5a_png/{z}/{x}/{y}.png",
    "DEM5B": "https://cyberjapandata.gsi.go.jp/xyz/dem5b_png/{z}/{x}/{y}.png",
    "DEM5C": "https://cyberjapandata.gsi.go.jp/xyz/dem5c_png/{z}/{x}/{y}.png",
    "DEM10B": "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png",
}

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


def split_qids(s):
    """wikidata_related は「;」区切りで複数可。"""
    return [q.strip() for q in (s or "").replace("；", ";").split(";") if q.strip()]


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
        for q in split_qids(r.get("wikidata_related")):
            if not re.fullmatch(r"Q\d+", q):
                problems.append(f"{rid}: wikidata_related の形が正しくありません（{q}）")
        for q in split_qids(r.get("water_source_river_qid")):
            if not re.fullmatch(r"Q\d+", q):
                problems.append(f"{rid}: water_source_river_qid の形が正しくありません（{q}）")
        if r.get("wikidata_qid") and r.get("wikidata_qid") in split_qids(r.get("wikidata_related")):
            problems.append(f"{rid}: 同じQIDが wikidata_qid と wikidata_related の両方にあります")
        if r.get("verified") == "1" and not r.get("wikidata_qid"):
            problems.append(f"{rid}: verified=1 なのに wikidata_qid が空です")
        by = r.get("built_year", "")
        if by and not by.isdigit():
            problems.append(f"{rid}: built_year は西暦の整数で（{by}）")
        elif by and y.isdigit() and int(y) - int(by) < 100:
            problems.append(f"{rid}: 登録基準（建設から100年以上）と矛盾します（built {by} / registered {y}）")
        if by and not r.get("built_year_basis"):
            problems.append(f"{rid}: built_year の根拠（built_year_basis）が空です")
        if by and r.get("built_period"):
            problems.append(f"{rid}: built_period（建設時期）は built_year が空のときだけ使います")
        ft = r.get("facility_type", "")
        if ft and ft not in FACILITY_TYPES:
            problems.append(f"{rid}: facility_type『{ft}』は語彙にありません（{sorted(FACILITY_TYPES)}）")
    return problems


def load_rows(path):
    """CSV をそのまま行のリストで読む（なければ空）。"""
    if path and Path(path).exists():
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    return []


def load_optional_csv(path):
    """data/images.csv や data/external_links.csv（なければ空）を id ごとにまとめて読む。"""
    out = {}
    if path and Path(path).exists():
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                out.setdefault(r["id"], []).append(r)
    return out


def build_graph(rows, base, pref_qids, dataset_meta, images=None, extlinks=None, terrain=None, addrlinks=None,
                river_flow=None, wd_labels=None):
    addrlinks = addrlinks or {}
    river_flow = river_flow or []
    images = images or {}
    extlinks = extlinks or {}
    terrain = terrain or {}
    base = base.rstrip("/") + "/"
    RES = Namespace(base + "resource/")
    WHIS = Namespace(base + "ontology#")

    g = Graph()
    for p, ns in [("schema", SCHEMA), ("geo", GEO), ("wgs84", WGS), ("wd", WD), ("whis", WHIS),
                  ("res", RES), ("dcterms", DCTERMS), ("dcat", DCAT), ("owl", OWL), ("skos", SKOS),
                  ("agrovoc", AGROVOC)]:
        g.bind(p, ns)

    # --- 最小限の独自語彙 ---
    g.add((WHIS.HeritageIrrigationStructure, RDF.type, OWL.Class))
    g.add((WHIS.HeritageIrrigationStructure, RDFS.subClassOf, SCHEMA.LandmarksOrHistoricalBuildings))
    g.add((WHIS.HeritageIrrigationStructure, RDFS.label, Literal("世界かんがい施設遺産", lang="ja")))
    g.add((WHIS.HeritageIrrigationStructure, RDFS.label, Literal("World Heritage Irrigation Structure", lang="en")))
    for prop, ja, en, rng in [
        (WHIS.registeredYear, "登録年", "year of registration", XSD.gYear),
        (WHIS.builtYear, "建設年（何の年かは builtYearBasis に記載）", "year built", XSD.gYear),
        (WHIS.facilityType, "施設の種類", "facility type", XSD.string),
        (WHIS.waterSource, "水源（川・湖など。Wikidataにあれば IRI）", "water source (river, lake, etc.)", None),
        (WHIS.waterSourceName, "水源の名前（資料の表記）", "name of the water source as written in the sources", None),
        (WHIS.prefectureCode, "都道府県コード（ISO 3166-2:JP）", "prefecture code", XSD.string),
        (WHIS.irrigatedArea, "かんがい面積（ha）", "irrigated area (ha)", XSD.decimal),
        (WHIS.managedBy, "管理者", "managing organization", XSD.string),
        (WHIS.builtYearBasis, "建設年の根拠（着工・完成・供用開始など）", "basis of built year", XSD.string),
        (WHIS.builtPeriod, "建設時期（資料に西暦の年がないとき、資料の表現のまま。年に換算していない）",
         "construction period as worded in the source (used only when no exact year is given)", XSD.string),
        (WHIS.representativePoint, "代表地点（座標を取る場所の名前）", "representative point name", XSD.string),
        (WHIS.pointAddress, "代表地点の住所（国土地理院の逆ジオコーダで座標から求めた市区町村・大字）",
         "address of the representative point (reverse-geocoded by GSI)", XSD.string),
        (WHIS.facilityCategory, "施設の種類（SKOS の概念。AGROVOC・Wikidata とつながる）",
         "facility category (SKOS concept linked to AGROVOC and Wikidata)", SKOS.Concept),
        (WHIS.pointElevation, "代表地点の標高（m。東京湾平均海面からの高さ。地理院タイルの標高タイルから求めた目安）",
         "elevation of the representative point in metres above mean sea level (from GSI DEM tiles)", XSD.decimal),
        (WHIS.pointAddressArea, "代表地点がある大字・町丁目（住所LOD の IRI）",
         "address area (oaza/chome) of the representative point in Linked Open Addresses Japan", None),
        (WHIS.pointMunicipality, "代表地点がある市区町村（統計LOD の標準地域コード）",
         "municipality of the representative point (standard area code in e-Stat statistical LOD)", None),
        (WHIS.pointElevationSource, "標高を求めた数値標高モデル（DEM1A＝1mメッシュ・航空レーザ測量、DEM5A＝5mメッシュ など）",
         "digital elevation model used for the elevation", XSD.string),
    ]:
        g.add((prop, RDF.type, RDF.Property))
        g.add((prop, RDFS.label, Literal(ja, lang="ja")))
        g.add((prop, RDFS.label, Literal(en, lang="en")))
        if rng is not None:
            g.add((prop, RDFS.range, rng))

    # --- 施設の種類（SKOS） ---
    scheme = WHIS["facilityTypeScheme"]
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    g.add((scheme, SKOS.prefLabel, Literal("世界かんがい施設遺産の施設の種類", lang="ja")))
    g.add((scheme, SKOS.prefLabel, Literal("Facility types of World Heritage Irrigation Structures", lang="en")))
    g.add((scheme, DCTERMS.source, URIRef("https://www.maff.go.jp/j/press/nousin/kaigai/attach/pdf/251201-1.pdf")))
    for ja, (slug, en, definition, matches) in FACILITY_TYPE_CONCEPTS.items():
        c = WHIS["type-" + slug]
        g.add((c, RDF.type, SKOS.Concept))
        g.add((c, SKOS.inScheme, scheme))
        g.add((c, SKOS.topConceptOf, scheme))
        g.add((scheme, SKOS.hasTopConcept, c))
        g.add((c, SKOS.prefLabel, Literal(ja, lang="ja")))
        g.add((c, SKOS.prefLabel, Literal(en, lang="en")))
        g.add((c, SKOS.definition, Literal(definition, lang="ja")))
        for rel, target in matches:
            g.add((c, getattr(SKOS, rel), target))

    # --- 水源の川がどこへ流れるか（Wikidata の「河口・流出先」P403 を写したもの。Wikidata は CC0） ---
    # 手元の SPARQL だけで「同じ水系の遺産」を調べられるようにする。data/river_flow.csv
    P403 = URIRef("http://www.wikidata.org/prop/direct/P403")
    g.bind("wdt", "http://www.wikidata.org/prop/direct/")
    for e in river_flow:
        a, b = WD[e["from_qid"]], WD[e["to_qid"]]
        g.add((a, P403, b))
        for q, lab in [(a, e.get("from_label")), (b, e.get("to_label"))]:
            if lab:
                g.add((q, RDFS.label, Literal(lab, lang="ja")))
    for x in (wd_labels or []):          # 水源の川・湖の Wikidata の日本語ラベル（CC0）
        g.add((WD[x["qid"]], RDFS.label, Literal(x["label_ja"], lang="ja")))

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
    g.add((ds, DCAT.landingPage, URIRef(base)))
    # 版と来歴（W3C PROV-O）：このデータが何から、いつ、どのプログラムで作られたか
    PROV = Namespace("http://www.w3.org/ns/prov#")
    g.bind("prov", PROV)
    g.add((ds, DCAT.version, Literal(dataset_meta["modified"])))
    for src in ["https://www.maff.go.jp/j/nousin/kaigai/ICID/his/abstruct.html",   # 農林水産省 登録施設の概要
                "https://maps.gsi.go.jp/development/ichiran.html",                 # 地理院タイル（標高・空中写真）
                "https://www.wikidata.org/", "https://commons.wikimedia.org/",
                "https://uedayou.net/loa/", "https://data.e-stat.go.jp/lodw/", "https://agrovoc.fao.org/"]:
        g.add((ds, PROV.wasDerivedFrom, URIRef(src)))
    act = URIRef(base + "dataset#build")
    g.add((ds, PROV.wasGeneratedBy, act))
    g.add((act, RDF.type, PROV.Activity))
    g.add((act, RDFS.label, Literal("CSV から RDF・サイトを作り、SHACL でチェックする処理（lod.py build）", lang="ja")))
    g.add((act, PROV.endedAtTime, Literal(dataset_meta.get("generated") or dataset_meta["modified"],
                                           datatype=XSD.dateTime if "T" in (dataset_meta.get("generated") or "") else XSD.date)))
    code = URIRef("https://github.com/ysh17-hub/whis-lod")
    g.add((act, PROV.used, code))
    sha = os.environ.get("GITHUB_SHA")
    if sha:   # GitHub Actions で作ったときは、どのコミットから作ったかも記録する
        g.add((act, PROV.used, URIRef(f"https://github.com/ysh17-hub/whis-lod/commit/{sha}")))
    g.add((ds, DCTERMS.spatial, WD["Q17"]))  # 日本
    g.add((ds, DCTERMS.language, URIRef("http://id.loc.gov/vocabulary/iso639-1/ja")))
    for kw in ["世界かんがい施設遺産", "World Heritage Irrigation Structures", "かんがい", "農業水利", "ICID"]:
        g.add((ds, DCAT.keyword, Literal(kw, lang="en" if kw.isascii() else "ja")))
    for fname, mtype, fmt in [("whis_japan.ttl", "text/turtle", "Turtle"),
                              ("whis_japan.jsonld", "application/ld+json", "JSON-LD"),
                              ("whis_japan.geojson", "application/geo+json", "GeoJSON"),
                              ("whis_japan.csv", "text/csv", "CSV")]:
        dist = URIRef(base + fname + "#distribution")
        g.add((ds, DCAT.distribution, dist))
        g.add((dist, RDF.type, DCAT.Distribution))
        g.add((dist, DCAT.downloadURL, URIRef(base + fname)))
        g.add((dist, DCAT.mediaType, URIRef("https://www.iana.org/assignments/media-types/" + mtype)))
        g.add((dist, DCTERMS.format, Literal(fmt)))
        g.add((dist, DCTERMS.license, URIRef(dataset_meta["license"])))

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
        if pref in PREF_CODE:   # 統計LOD の都道府県の標準地域コード（2026-11-23、統計LOD の SPARQL で確認：C○○000-19700401）
            g.add((s, SCHEMA.containedInPlace, URIRef(f"http://data.e-stat.go.jp/lod/sac/C{PREF_CODE[pref]}000-19700401")))
        if r.get("municipality"):
            g.add((s, SCHEMA.addressLocality, Literal(r["municipality"], lang="ja")))

        # 年
        if r.get("registered_year"):
            g.add((s, WHIS.registeredYear, Literal(r["registered_year"], datatype=XSD.gYear)))
        if r.get("built_year"):
            g.add((s, WHIS.builtYear, Literal(r["built_year"].zfill(4), datatype=XSD.gYear)))
        if r.get("built_year_basis"):
            g.add((s, WHIS.builtYearBasis, Literal(r["built_year_basis"], lang="ja")))
        if r.get("built_period"):
            g.add((s, WHIS.builtPeriod, Literal(r["built_period"], lang="ja")))
        if r.get("representative_point"):
            g.add((s, WHIS.representativePoint, Literal(r["representative_point"], lang="ja")))
        if r.get("point_address"):
            g.add((s, WHIS.pointAddress, Literal(r["point_address"], lang="ja")))

        # 種類・水源・管理者・面積
        if r.get("facility_type"):
            g.add((s, WHIS.facilityType, Literal(r["facility_type"], lang="ja")))
            if r["facility_type"] in FACILITY_TYPE_CONCEPTS:
                g.add((s, WHIS.facilityCategory, WHIS["type-" + FACILITY_TYPE_CONCEPTS[r["facility_type"]][0]]))
        # 代表地点の住所の IRI（住所LOD）と市区町村（統計LOD の標準地域コード）。data/address_links.csv
        for al in addrlinks.get(r["id"], [])[:1]:
            if al.get("loa_uri"):
                g.add((s, WHIS.pointAddressArea, URIRef(al["loa_uri"])))
            if al.get("sac_uri"):
                g.add((s, WHIS.pointMunicipality, URIRef(al["sac_uri"])))
        # 代表地点の標高（data/point_terrain.csv。地理院タイルの標高タイルから求めた値）
        # 座標を直したのに標高が古いままにならないよう、求めたときの座標が今の座標と同じときだけ使う
        for t in terrain.get(r["id"], [])[:1]:
            same_point = (t.get("lat") and parse_float(r.get("lat")) is not None
                          and abs(float(t["lat"]) - float(r["lat"])) < 1e-7 and abs(float(t["lon"]) - float(r["lon"])) < 1e-7)
            if not same_point:
                print(f"警告: {r['id']} の標高は前の座標で求めたものなので使いません（python scripts/terrain.py で計算し直せます）",
                      file=sys.stderr)
                continue
            if t.get("elevation_m"):
                g.add((s, WHIS.pointElevation, Literal(t["elevation_m"], datatype=XSD.decimal)))
                g.add((s, WHIS.pointElevationSource, Literal(t.get("elevation_dem", ""))))
        river_qids = split_qids(r.get("water_source_river_qid"))
        for q in river_qids:
            g.add((s, WHIS.waterSource, WD[q]))
        if r.get("water_source_river"):
            g.add((s, WHIS.waterSourceName, Literal(r["water_source_river"], lang="ja")))
            if not river_qids:
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
        for q in split_qids(r.get("wikidata_related")):
            g.add((s, SCHEMA.hasPart, WD[q]))
        if r.get("icid_page_url"):
            g.add((s, RDFS.seeAlso, URIRef(r["icid_page_url"])))
        for u in split_urls(r.get("source_url")):
            g.add((s, DCTERMS.source, URIRef(u)))
        # 写真（Wikidata の P18 にある Wikimedia Commons の画像。作者とライセンスつき）
        for im in images.get(r["id"], []):
            img = URIRef(im["file_page"])
            g.add((s, SCHEMA.image, img))
            g.add((img, RDF.type, SCHEMA.ImageObject))
            g.add((img, SCHEMA.contentUrl, URIRef(im["image_url"])))
            g.add((img, SCHEMA.name, Literal(im["file"])))
            if im.get("artist"):
                g.add((img, SCHEMA.creditText, Literal(im["artist"])))
            if im.get("license_url"):
                g.add((img, SCHEMA.license, URIRef(im["license_url"])))
            elif im.get("license"):
                g.add((img, SCHEMA.license, Literal(im["license"])))
            g.add((img, SCHEMA.about, WD[im["qid"]]))
        # 外部データベース：遺産と「同じ施設」の Wikidata 項目にある外部ID（GeoNames、OpenStreetMap など）
        for ex in extlinks.get(r["id"], []):
            if ex.get("relation") == "same":
                g.add((s, RDFS.seeAlso, URIRef(ex["url"])))
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
                  "built_year", "built_year_basis", "built_period", "facility_type", "water_source_river", "managing_org",
                  "irrigated_area_ha", "representative_point", "point_address", "wikidata_qid", "wikidata_related",
                  "water_source_river_qid", "verified", "source_url", "note"]}
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
    ap.add_argument("--images", default=None)
    ap.add_argument("--extlinks", default=None)
    ap.add_argument("--terrain", default=None)
    ap.add_argument("--addrlinks", default=None)
    ap.add_argument("--riverflow", default=None)
    ap.add_argument("--wdlabels", default=None)
    a = ap.parse_args(argv)

    with open(a.csv, encoding="utf-8-sig") as f:
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
    g = build_graph(rows, a.base, load_pref_qids(a.prefqid), meta,
                    load_optional_csv(a.images), load_optional_csv(a.extlinks), load_optional_csv(a.terrain),
                    load_optional_csv(a.addrlinks), load_rows(a.riverflow),
                    load_rows(a.wdlabels))
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
