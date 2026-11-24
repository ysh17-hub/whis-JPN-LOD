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
    ("facilityType", "文字列", "施設の種類（水路・ため池・堰・用水群・揚水機場）。農林水産省が示す対象施設の例（ダム、ため池などの貯水施設、堰・分水施設、水路など）を参考に作成者が分類した。"),
    ("waterSource", "Wikidataの項目（なければ文字列）", "水源の川・湖など。Wikidata に同じ川・湖の項目があるときは、その IRI で示す（複数あり得る）。"),
    ("waterSourceName", "文字列", "水源の名前を資料の表記のまま記録したもの（例：奥入瀬川（十和田湖））。"),
    ("prefectureCode", "文字列", "都道府県コード（ISO 3166-2:JP 形式、例: JP-04）。"),
    ("irrigatedArea", "xsd:decimal", "かんがい面積（ha）。資料によって値が異なるものは空欄にし、comment に両方を書いた。"),
    ("managedBy", "文字列", "管理者（土地改良区など）。"),
    ("representativePoint", "文字列", "座標を取った代表地点の名前（取水口・堰・池など）。"),
    ("facilityCategory", "SKOS の概念", "施設の種類を、下の「施設の種類（SKOS）」の概念で表したもの。国連食糧農業機関（FAO）の多言語シソーラス AGROVOC と Wikidata のクラスにつながる。"),
    ("pointElevation", "数値（m）", "代表地点の標高（東京湾平均海面からの高さ）。国土地理院の標高タイル（地理院タイル）で、細かいものから順に 1mメッシュ（DEM1A）→5mメッシュ（DEM5A→DEM5B→DEM5C）→10mメッシュ（DEM10B）の値を使った（地理院地図の標高表示と同じ順）。池や川の上の点は水面の高さになる。目安の値。"),
    ("pointAddressArea", "IRI（住所LOD）", "代表地点がある大字・町丁目を表す、住所LOD（Linked Open Addresses Japan）の IRI。住所LODに大字の項目がないときは市区町村の IRI。"),
    ("pointMunicipality", "IRI（統計LOD）", "代表地点がある市区町村を表す、統計LOD（政府統計の総合窓口 e-Stat）の標準地域コードの IRI。人口などの統計とつなげられる。"),
    ("pointElevationSource", "文字列", "標高を求めた数値標高モデルの種類（DEM1A＝航空レーザ測量の1mメッシュ、DEM5A＝5mメッシュ、DEM10B＝10mメッシュ など）。"),
    ("pointAddress", "文字列", "代表地点の座標がある場所の住所（市区町村・大字）。国土地理院の逆ジオコーダで座標から求めた。川の上の堰などは、隣の市町村になることがある。"),
]

FIELD_LABELS = [
    ("name_en", "英語名"), ("prefecture", "都道府県"), ("municipality", "市町村"),
    ("registered_year", "登録年"), ("built_year", "建設年"), ("built_year_basis", "建設年の根拠"),
    ("facility_type", "種類"), ("water_source_river", "水源"), ("managing_org", "管理者"),
    ("irrigated_area_ha", "かんがい面積（ha）"), ("representative_point", "代表地点"),
    ("point_address", "代表地点の住所（座標から）"),
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
        "url": uri,
        "isPartOf": base + "dataset",
        "citation": conv.split_urls(r.get("source_url")),
    }
    lat, lon = conv.parse_float(r.get("lat")), conv.parse_float(r.get("lon"))
    if lat is not None and lon is not None:
        d["geo"] = {"@type": "GeoCoordinates", "latitude": lat, "longitude": lon}
    if r.get("verified") == "1" and r.get("wikidata_qid"):
        d["sameAs"] = "http://www.wikidata.org/entity/" + r["wikidata_qid"]
    rel = conv.split_qids(r.get("wikidata_related"))
    if rel:
        d["hasPart"] = [{"@id": "http://www.wikidata.org/entity/" + q} for q in rel]
    return d


def add_media(d, imgs, exts):
    if imgs:
        d["image"] = [{"@type": "ImageObject", "contentUrl": im["image_url"], "url": im["file_page"],
                       "creditText": im.get("artist", ""), "license": im.get("license_url") or im.get("license", "")}
                      for im in imgs]
    same_ext = [x["url"] for x in (exts or []) if x["relation"] == "same"]
    if same_ext:
        d["subjectOf"] = same_ext
    return d


LIGHTBOX = """<div id="lb" onclick="if(event.target===this)this.style.display='none'"><div><img id="lbimg" alt=""><p id="lbcap"></p><button onclick="document.getElementById('lb').style.display='none'">閉じる</button></div></div>
<script>
function openImg(a){var d=a.dataset;document.getElementById('lbimg').src=d.big;document.getElementById('lbimg').alt=d.alt;
document.getElementById('lbcap').innerHTML=d.cap;document.getElementById('lb').style.display='flex';return false;}
document.addEventListener('keydown',function(e){if(e.key==='Escape')document.getElementById('lb').style.display='none';});
</script>"""

PAGE_CSS = """body{font-family:system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;max-width:820px;margin:24px auto;padding:0 16px;line-height:1.6}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #eee;padding:6px;text-align:left;vertical-align:top}
th{width:11em;color:#444}code{background:#f4f4f4;padding:1px 4px}nav a{margin-right:12px}small{color:#666}
.gallery{display:flex;flex-wrap:wrap;gap:12px}.gallery figure{margin:0;width:240px}.gallery img{width:240px;height:170px;object-fit:cover;border-radius:4px;cursor:zoom-in;display:block}
.gallery figcaption{font-size:12px;color:#555;line-height:1.4;margin-top:4px}
#lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:9999;align-items:center;justify-content:center}
#lb>div{max-width:92vw;max-height:92vh;text-align:center;color:#fff}#lb img{max-width:92vw;max-height:78vh}#lb p{font-size:13px}#lb a{color:#9cf}
#lb button{font-size:14px;padding:4px 14px}"""


def gallery_html(imgs):
    """Wikimedia Commons の写真（押すと大きく表示。作者・ライセンス・出典つき）。"""
    if not imgs:
        return ""
    e = html.escape
    figs = []
    for im in imgs:
        lic = (f'<a href="{e(im["license_url"])}">{e(im["license"])}</a>' if im.get("license_url") else e(im.get("license", "")))
        who = ("" if im["relation"] == "same" else f"構成施設「{e(im['label'])}」　")
        cap = (f'{who}撮影：{e(im.get("artist", ""))}／{lic}／'
               f'<a href="{e(im["file_page"])}">Wikimedia Commons</a>')
        figs.append(
            f'<figure><a href="{e(im["file_page"])}" onclick="return openImg(this)" '
            f'data-big="{e(im["image_url"])}?width=1280" data-alt="{e(im["label"])}" data-cap="{e(cap)}">'
            f'<img src="{e(im["image_url"])}?width=500" alt="{e(im["label"])}の写真" loading="lazy"></a>'
            f'<figcaption>{cap}</figcaption></figure>')
    return ('<h2>写真</h2><p><small>Wikidata の項目に登録されている Wikimedia Commons の写真です。押すと大きく表示されます。'
            'このデータセットのライセンス（CC BY 4.0）ではなく、各写真のライセンスに従います。</small></p>'
            f'<div class="gallery">{"".join(figs)}</div>')


def ext_html(exts):
    """Wikidata 経由でつながる外部のデータベース・百科事典。"""
    if not exts:
        return ""
    e = html.escape
    items = []
    for x in exts:
        who = "" if x["relation"] == "same" else f"（構成施設「{e(x['label'])}」）"
        items.append(f'<li>{e(x["source_label"])}{who}：<a href="{e(x["url"])}">{e(x["value"])}</a></li>')
    return ('<h2>ほかのデータベース・百科事典</h2><p><small>つながっている Wikidata の項目に登録されている外部ID・記事です'
            f'（{e(exts[0].get("retrieved", ""))} 時点）。</small></p><ul>{"".join(items)}</ul>')


def dead_sources():
    """公開元から消えた出典（data/source_status.csv の status=消失）。ページに「リンク切れ」と出す。"""
    p = ROOT / "data" / "source_status.csv"
    return {x["url"]: x for x in conv.load_rows(str(p)) if x.get("status") == "消失"} if p.exists() else {}


def current_terrain(r, terrain):
    """今の座標で求めた標高・空中写真の記録だけを返す（座標を直したあとの古い値は使わない）。"""
    t = (terrain or [{}])[0]
    try:
        if abs(float(t["lat"]) - float(r["lat"])) < 1e-7 and abs(float(t["lon"]) - float(r["lon"])) < 1e-7:
            return t
    except (KeyError, ValueError, TypeError):
        pass
    return {}


def aerial_html(r, terrain):
    """代表地点の航空写真（最新・昔）と地形を、その場で切り替えて見る小さな地図。"""
    if not (r.get("lat") and r.get("lon")):
        return ""
    e = html.escape
    t = current_terrain(r, terrain)
    avail = [k for k, col in [("p1974", "aerial_1974_1978"), ("p1961", "aerial_1961_1969"), ("p1945", "aerial_1945_1950")]
             if t.get(col) == "1"]
    years = "・".join(lbl for k, lbl in [("p1945", "1945〜1950年"), ("p1961", "1961〜1969年"), ("p1974", "1974〜1978年")] if k in avail)
    lat, lon = float(r["lat"]), float(r["lon"])
    gsi = f"https://maps.gsi.go.jp/#17/{lat:.6f}/{lon:.6f}/&base=std&ls=std%7Cseamlessphoto&disp=01"
    return f"""<h2>航空写真・地形で見る</h2>
<p><small>代表地点（{e(r.get('representative_point') or '—')}）のまわりです。右上で背景を「航空写真（最新）」「色別標高図」などに切り替えられます。
この地点で見つかった昔の空中写真：{e(years or 'なし')}。「昔の航空写真を重ねる」で選び、「濃さ」を動かすと今と比べられます。
（出典：国土地理院 地理院タイル）　<a href="{e(gsi)}">地理院地図で開く</a></small></p>
<div id="amap" style="height:380px;border-radius:6px"></div>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="../gsi_layers.js"></script>
<script>
(function(){{
  if (!window.L || !window.WHIS_GSI) {{ document.getElementById('amap').textContent = '地図を読み込めませんでした。'; return; }}
  const m = L.map('amap', {{ scrollWheelZoom: false }}).setView([{lat}, {lon}], 16);
  WHIS_GSI.setup(m, {{ base: '航空写真（最新）', available: {json.dumps(avail)}, collapsed: true }});
  L.circleMarker([{lat}, {lon}], {{ radius: 8, weight: 2, color: '#fff', fillColor: '#e53e3e', fillOpacity: 1 }})
    .bindTooltip({json.dumps(r.get('representative_point') or r['name_ja'], ensure_ascii=False)}).addTo(m);
}})();
</script>"""


def resource_page(r, base, creator, imgs=None, exts=None, terrain=None, addr=None):
    e = html.escape
    t = current_terrain(r, terrain)
    al = (addr or [{}])[0]

    def cell(k):
        v = e(r.get(k, "") or "—")
        if k == "water_source_river":
            qs = conv.split_qids(r.get("water_source_river_qid"))
            if qs:
                v += "（Wikidata：" + "、".join(f'<a href="https://www.wikidata.org/wiki/{e(q)}">{e(q)}</a>' for q in qs) + "）"
        if k == "facility_type" and r.get(k) in conv.FACILITY_TYPE_CONCEPTS:
            slug = conv.FACILITY_TYPE_CONCEPTS[r[k]][0]
            v = f'<a href="../ontology.html#type-{e(slug)}">{v}</a>'
        if k == "point_address" and t.get("elevation_m"):
            v += f"（標高 約{e(t['elevation_m'])}m・{e(t.get('elevation_dem', ''))}）"
        if k == "point_address" and (al.get("loa_uri") or al.get("sac_uri")):
            links = []
            if al.get("loa_uri"):
                links.append(f'<a href="{e(al["loa_uri"])}">住所LOD</a>')
            if al.get("sac_uri"):
                links.append(f'<a href="{e(al["sac_uri"])}">統計LOD（標準地域コード {e(al.get("municipality_code", ""))}）</a>')
            v += "<br><small>" + "／".join(links) + "</small>"
        return v
    rows = "".join(f"<tr><th>{e(lbl)}</th><td>{cell(k)}</td></tr>" for k, lbl in FIELD_LABELS)
    wd = (f'<a href="https://www.wikidata.org/wiki/{e(r["wikidata_qid"])}">{e(r["wikidata_qid"])}</a>（確認済み）'
          if r.get("verified") == "1" and r.get("wikidata_qid") else ("—" if not r.get("wikidata_related") else ""))
    rel = conv.split_qids(r.get("wikidata_related"))
    if rel:
        wd += "<br>構成施設：" + "、".join(f'<a href="https://www.wikidata.org/wiki/{e(q)}">{e(q)}</a>' for q in rel)
    dead = dead_sources()
    srcs = "".join(
        f'<li><a href="{e(u)}">{e(u)}</a>'
        + (f' <small>（リンク切れ：公開元から削除されました。{e(dead[u]["checked"])}確認。データ作成時に参照した資料）</small>' if u in dead else "")
        + '</li>' for u in conv.split_urls(r.get("source_url")))
    ld = json.dumps(add_media(jsonld_for(r, base), imgs, exts), ensure_ascii=False, indent=1).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(r['name_ja'])}｜世界かんがい施設遺産（日本）LOD</title>
<link rel="alternate" type="text/turtle" href="{e(r['id'])}.ttl">
<link rel="alternate" type="application/ld+json" href="{e(r['id'])}.jsonld">
<style>{PAGE_CSS}</style>
<script type="application/ld+json">
{ld}
</script></head><body>
<nav><a href="../index.html">地図</a><a href="../sparql.html">SPARQL</a><a href="../ontology.html">語彙</a><a href="../watersystems.html">水系</a><a href="../quality.html">検証</a><a href="../whis_japan.ttl">全体のTurtle</a><a href="../whis_japan.csv">CSV</a><a href="../en.html">English</a></nav>
<h1>{e(r['name_ja'])}</h1>
<p><small>URI: <code>{e(base + 'resource/' + r['id'])}</code>　この施設のデータ：<a href="{e(r['id'])}.ttl">Turtle</a>／<a href="{e(r['id'])}.jsonld">JSON-LD</a></small></p>
<table>{rows}<tr><th>Wikidata</th><td>{wd}</td></tr></table>
{gallery_html(imgs or [])}
{aerial_html(r, terrain)}
{ext_html(exts or [])}
<h2>出典</h2><ul>{srcs}</ul>
<p><small>データ: CC BY 4.0（作成: {e(creator)}）。数値は出典に書かれた範囲のみを記載し、資料で値が異なるものは空欄にして注記に両方を書いています。</small></p>
{LIGHTBOX}
</body></html>
"""


def ontology_page(base):
    e = html.escape
    rows = "".join(f'<tr id="{e(t)}"><th><code>whis:{e(t)}</code></th><td>{e(k)}</td><td>{e(d)}</td></tr>'
                   for t, k, d in ONTOLOGY_TERMS)

    def target(u):
        u = str(u)
        if u.startswith("http://aims.fao.org/aos/agrovoc/"):
            cid = u.rsplit("/", 1)[1]
            return f'<a href="https://agrovoc.fao.org/browse/agrovoc/en/page/{e(cid)}">AGROVOC {e(cid)}</a>'
        if u.startswith("http://www.wikidata.org/entity/"):
            q = u.rsplit("/", 1)[1]
            return f'<a href="https://www.wikidata.org/wiki/{e(q)}">Wikidata {e(q)}</a>'
        return e(u)
    concepts = "".join(
        f'<tr id="type-{e(slug)}"><th><code>whis:type-{e(slug)}</code><br>{e(ja)}／{e(en)}</th><td>{e(d)}</td>'
        f'<td>{"<br>".join(f"<code>skos:{e(rel)}</code> {target(u)}" for rel, u in m)}</td></tr>'
        for ja, (slug, en, d, m) in conv.FACILITY_TYPE_CONCEPTS.items())
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>語彙 whis:｜世界かんがい施設遺産（日本）LOD</title><style>{PAGE_CSS}</style></head><body>
<nav><a href="index.html">地図</a><a href="sparql.html">SPARQL</a><a href="quality.html">検証</a><a href="whis_japan.ttl">Turtle</a><a href="shapes.ttl">SHACL</a><a href="en.html">English</a></nav>
<h1>独自語彙 whis:</h1>
<p>名前空間: <code>{e(base)}ontology#</code><br>
既存の語彙（schema.org、GeoSPARQL、W3C Basic Geo、DCMI Terms、DCAT、OWL）で表せない項目だけを定義しています。</p>
<table><tr><th>用語</th><td><b>値</b></td><td><b>説明</b></td></tr>{rows}</table>
<h2 id="facilityTypeScheme">施設の種類（SKOS）</h2>
<p>農林水産省が示す世界かんがい施設遺産の対象施設の例（ダム、ため池などの貯水施設、堰・分水施設、水路など）を参考に作成者が分類し、
国連食糧農業機関（FAO）の多言語シソーラス <a href="https://agrovoc.fao.org/">AGROVOC</a> と Wikidata のクラスに結びました（2026-11-23 確認）。
意味の範囲が完全に同じとは言えないものは <code>skos:closeMatch</code>、相手のほうが広いものは <code>skos:broadMatch</code> です。</p>
<table><tr><th>概念</th><td><b>説明</b></td><td><b>AGROVOC・Wikidata</b></td></tr>{concepts}</table>
</body></html>
"""


def void_ttl(g, base):
    """VoID（データセットの説明）。ほかのデータとのつながり（リンクセット）の数を数えて書く。"""
    from rdflib import Graph, Literal, Namespace, URIRef, RDF
    from rdflib.namespace import DCTERMS, OWL, RDFS, SKOS, XSD
    VOID = Namespace("http://rdfs.org/ns/void#")
    SCHEMA = Namespace("https://schema.org/")
    WHIS = Namespace(base + "ontology#")
    v = Graph()
    v.bind("void", VOID); v.bind("dcterms", DCTERMS)
    ds = URIRef(base + "void.ttl#dataset")
    v.add((ds, RDF.type, VOID.Dataset))
    v.add((ds, DCTERMS.title, Literal("世界かんがい施設遺産（日本）Linked Open Data", lang="ja")))
    v.add((ds, DCTERMS.title, Literal("World Heritage Irrigation Structures in Japan as Linked Open Data", lang="en")))
    v.add((ds, DCTERMS.license, URIRef("https://creativecommons.org/licenses/by/4.0/")))
    v.add((ds, VOID.dataDump, URIRef(base + "whis_japan.ttl")))
    v.add((ds, VOID.uriSpace, Literal(base + "resource/")))
    v.add((ds, VOID.exampleResource, URIRef(base + "resource/WHIS-JP-026")))
    v.add((ds, VOID.triples, Literal(len(g), datatype=XSD.integer)))
    ents = set(g.subjects(RDF.type, WHIS.HeritageIrrigationStructure))
    v.add((ds, VOID.entities, Literal(len(ents), datatype=XSD.integer)))
    v.add((ds, DCTERMS.subject, URIRef("http://www.wikidata.org/entity/Q22127466")))
    v.add((ds, RDFS.seeAlso, URIRef(base + "dataset")))
    for ns in ["https://schema.org/", "http://www.opengis.net/ont/geosparql#", "http://www.w3.org/2003/01/geo/wgs84_pos#",
               "http://purl.org/dc/terms/", "http://www.w3.org/ns/dcat#", "http://www.w3.org/2004/02/skos/core#",
               "http://www.w3.org/2002/07/owl#", base + "ontology#"]:
        v.add((ds, VOID.vocabulary, URIRef(ns)))
    targets = {
        "wikidata": ("Wikidata", "https://www.wikidata.org/", "http://www.wikidata.org/entity/"),
        "agrovoc": ("AGROVOC", "https://agrovoc.fao.org/", "http://aims.fao.org/aos/agrovoc/"),
        "commons": ("Wikimedia Commons", "https://commons.wikimedia.org/", "https://commons.wikimedia.org/"),
        "jawiki": ("ウィキペディア日本語版", "https://ja.wikipedia.org/", "https://ja.wikipedia.org/"),
        "osm": ("OpenStreetMap", "https://www.openstreetmap.org/", "https://www.openstreetmap.org/"),
        "geonames": ("GeoNames", "https://www.geonames.org/", "https://sws.geonames.org/"),
        "ndl": ("国立国会図書館典拠", "https://id.ndl.go.jp/", "https://id.ndl.go.jp/"),
        "kunishitei": ("国指定文化財等データベース", "https://kunishitei.bunka.go.jp/", "https://kunishitei.bunka.go.jp/"),
        "bunka": ("文化遺産オンライン", "https://bunka.nii.ac.jp/", "https://bunka.nii.ac.jp/"),
        "loa": ("住所LOD（Linked Open Addresses Japan）", "https://uedayou.net/loa/", "https://uedayou.net/loa/"),
        "estat": ("統計LOD（標準地域コード）", "https://data.e-stat.go.jp/lodw/", "http://data.e-stat.go.jp/lod/sac/"),
    }
    # 都道府県（schema:containedInPlace）も数える
    for key, (title, home, prefix) in targets.items():
        t = URIRef(base + "void.ttl#" + key)
        v.add((t, RDF.type, VOID.Dataset)); v.add((t, DCTERMS.title, Literal(title))); v.add((t, VOID.uriSpace, Literal(prefix)))
        v.add((t, RDFS.seeAlso, URIRef(home)))
    for pred, name in [(OWL.sameAs, "sameAs"), (SCHEMA.hasPart, "hasPart"), (WHIS.waterSource, "waterSource"),
                       (RDFS.seeAlso, "seeAlso"), (SCHEMA.image, "image"),
                       (WHIS.pointAddressArea, "pointAddressArea"), (WHIS.pointMunicipality, "pointMunicipality"),
                       (SCHEMA.containedInPlace, "containedInPlace"),
                       (SKOS.exactMatch, "exactMatch"), (SKOS.closeMatch, "closeMatch"), (SKOS.broadMatch, "broadMatch")]:
        counts = {}
        for o in g.objects(None, pred):
            if not isinstance(o, URIRef):
                continue
            for key, (_, _, prefix) in targets.items():
                if str(o).startswith(prefix):
                    counts[key] = counts.get(key, 0) + 1
                    break
        for key, n in counts.items():
            ls = URIRef(base + f"void.ttl#{name}-{key}")
            v.add((ds, VOID.subset, ls))
            v.add((ls, RDF.type, VOID.Linkset))
            v.add((ls, VOID.linkPredicate, pred))
            v.add((ls, VOID.subjectsTarget, ds))
            v.add((ls, VOID.objectsTarget, URIRef(base + "void.ttl#" + key)))
            v.add((ls, VOID.triples, Literal(n, datatype=XSD.integer)))
    return v.serialize(format="turtle")


PREF_EN = {
    "北海道": "Hokkaido", "青森県": "Aomori", "岩手県": "Iwate", "宮城県": "Miyagi", "秋田県": "Akita", "山形県": "Yamagata",
    "福島県": "Fukushima", "茨城県": "Ibaraki", "栃木県": "Tochigi", "群馬県": "Gunma", "埼玉県": "Saitama", "千葉県": "Chiba",
    "東京都": "Tokyo", "神奈川県": "Kanagawa", "新潟県": "Niigata", "富山県": "Toyama", "石川県": "Ishikawa", "福井県": "Fukui",
    "山梨県": "Yamanashi", "長野県": "Nagano", "岐阜県": "Gifu", "静岡県": "Shizuoka", "愛知県": "Aichi", "三重県": "Mie",
    "滋賀県": "Shiga", "京都府": "Kyoto", "大阪府": "Osaka", "兵庫県": "Hyogo", "奈良県": "Nara", "和歌山県": "Wakayama",
    "鳥取県": "Tottori", "島根県": "Shimane", "岡山県": "Okayama", "広島県": "Hiroshima", "山口県": "Yamaguchi", "徳島県": "Tokushima",
    "香川県": "Kagawa", "愛媛県": "Ehime", "高知県": "Kochi", "福岡県": "Fukuoka", "佐賀県": "Saga", "長崎県": "Nagasaki",
    "熊本県": "Kumamoto", "大分県": "Oita", "宮崎県": "Miyazaki", "鹿児島県": "Kagoshima", "沖縄県": "Okinawa",
}


def english_page(rows, base, terrain, imgs):
    """英語の入口ページ（海外の人・研究者向け）。施設ページは日本語なので、一覧と使い方を英語で示す。"""
    e = html.escape
    trs = []
    for r in rows:
        t = current_terrain(r, terrain.get(r["id"]))
        ft = conv.FACILITY_TYPE_CONCEPTS.get(r.get("facility_type", ""), ("", "", "", []))[1]
        wd = (f'<a href="https://www.wikidata.org/wiki/{e(r["wikidata_qid"])}">{e(r["wikidata_qid"])}</a>'
              if r.get("verified") == "1" and r.get("wikidata_qid") else "")
        name = e(r.get("name_en") or "") or f'<span lang="ja">{e(r["name_ja"])}</span>'
        trs.append(f'<tr><td>{e(r["id"].replace("WHIS-JP-", ""))}</td><td><a href="resource/{e(r["id"])}.html">{name}</a>'
                   f'{"" if not r.get("name_en") else "<br><small lang=ja>" + e(r["name_ja"]) + "</small>"}</td>'
                   f'<td>{e(PREF_EN.get(r["prefecture"], r["prefecture"]))}</td><td>{e(ft)}</td><td>{e(r["registered_year"])}</td>'
                   f'<td>{e(r.get("built_year") or "")}</td><td>{e(t.get("elevation_m", ""))}</td><td>{wd}</td>'
                   f'<td>{"✓" if imgs.get(r["id"]) else ""}</td></tr>')
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>World Heritage Irrigation Structures in Japan as Linked Open Data</title>
<link rel="alternate" hreflang="ja" href="index.html"><style>{PAGE_CSS}table{{font-size:13px}}</style></head><body>
<nav><a href="index.html">Map (Japanese)</a><a href="sparql.html">SPARQL</a><a href="ontology.html">Vocabulary</a><a href="quality.html">Quality report</a><a href="https://github.com/ysh17-hub/whis-lod">GitHub</a></nav>
<h1>World Heritage Irrigation Structures in Japan as Linked Open Data</h1>
<p>This dataset describes all {len(rows)} World Heritage Irrigation Structures (WHIS) in Japan recognized by the International Commission on Irrigation and Drainage (ICID) from 2014 to 2026. Every record cites its sources (official documents of the Ministry of Agriculture, Forestry and Fisheries, prefectures, municipalities and land improvement districts). Values that differ between sources are left blank and both values are recorded in a note.</p>
<ul>
<li><b>Data</b>: <a href="whis_japan.ttl">Turtle</a> · <a href="whis_japan.jsonld">JSON-LD</a> · <a href="whis_japan.geojson">GeoJSON</a> · <a href="whis_japan.csv">CSV</a> · <a href="void.ttl">VoID</a> · <a href="shapes.ttl">SHACL shapes</a> — licence <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a> (photos keep their own licences)</li>
<li><b>URIs</b>: one URI per structure, e.g. <code>{e(base)}resource/WHIS-JP-026</code> (Manno-ike), with HTML, Turtle and JSON-LD.</li>
<li><b>Links</b>: Wikidata (same structure / components / water-source rivers), Linked Open Addresses Japan, e-Stat statistical LOD (standard area codes), FAO AGROVOC (facility types), OpenStreetMap, GeoNames and others.</li>
<li><b>Elevation</b> of each representative point from GSI DEM tiles (1 m mesh first), cross-checked against the GSI elevation service.</li>
<li><b>Map</b>: switch to aerial imagery or a colour relief map and overlay historical aerial photographs (1945–1950, 1961–1969, 1974–1978) from the Geospatial Information Authority of Japan.</li>
</ul>
<h2>All structures</h2>
<p><small>Names are shown in English where an official English name was found in the sources; otherwise in Japanese. Elevation is that of the representative point (m above mean sea level).</small></p>
<div style="overflow-x:auto"><table><tr><th>ID</th><th>Name</th><th>Prefecture</th><th>Type</th><th>Recognized</th><th>Built</th><th>Elevation (m)</th><th>Wikidata</th><th>Photo</th></tr>{"".join(trs)}</table></div>
<p><small>Map tiles, aerial photographs and elevation: <a href="https://maps.gsi.go.jp/development/ichiran.html">GSI Tiles (Geospatial Information Authority of Japan)</a>.</small></p>
</body></html>
"""


def quality_page(rows, base, terrain, addr, imgs, g, today):
    """検証レポート：どんなチェックをして、何件が合格したかを1ページで見せる。"""
    e = html.escape
    n = len(rows)
    t_ok = [current_terrain(r, terrain.get(r["id"])) for r in rows]
    elev = sum(1 for t in t_ok if t.get("elevation_m"))
    from decimal import Decimal, ROUND_HALF_UP
    mesh = {"DEM1A": "1m", "DEM5A": "5m", "DEM5B": "5m", "DEM5C": "5m", "DEM10B": "10m"}
    checked = same = 0
    for t in t_ok:
        if t.get("gsi_elevation_api_m"):
            checked += 1
            m = mesh.get(t.get("elevation_dem"), "")
            q = Decimal("1") if m == "10m" else Decimal("0.1")
            same += (Decimal(t["elevation_m"]).quantize(q, ROUND_HALF_UP) == Decimal(t["gsi_elevation_api_m"]).quantize(q, ROUND_HALF_UP)
                     and t.get("gsi_elevation_api_mesh") == m)
    loa = sum(1 for r in rows if (addr.get(r["id"]) or [{}])[0].get("loa_uri"))
    sac = sum(1 for r in rows if (addr.get(r["id"]) or [{}])[0].get("sac_uri"))
    all_src = {u for r in rows for u in conv.split_urls(r.get("source_url"))}
    srcs = len(all_src)
    n_dead = len(all_src & set(dead_sources()))
    maff_pdf = sum(1 for r in rows if any("/ICID/his/attach/pdf/" in u for u in conv.split_urls(r.get("source_url"))))
    same_wd = sum(1 for r in rows if r.get("verified") == "1" and r.get("wikidata_qid"))
    checked_wd = sum(1 for r in rows if r.get("wikidata_checked") == "1")
    n_img = sum(len(v) for v in imgs.values())
    checks = [
        ("出典", f"{n}/{n} 施設に出典URL（重複を除いて {srcs} 件の資料）。{maff_pdf}/{n} 施設に農林水産省の施設概要PDF（現行の番号）。公開元から消えた出典 {n_dead} 件は「リンク切れ」と表示",
         "出典URLのない行があると、SHACL のチェックで止まって公開されない。農林水産省の施設概要PDFは、登録施設の概要ページの現在のリンクと照合（2026-11-24）"),
        ("データの形（SHACL）", "%%SHACL_RESULT%%",
         "IDの形・登録年の型・座標の範囲・出典の有無・写真のライセンス・リンク先の形など。更新のたびに自動でチェック（shacl_report.txt）"),
        ("座標", f"{sum(1 for r in rows if r.get('lat'))}/{n} 施設", "代表地点を航空写真で確かめて1点ずつ入力"),
        ("標高", f"{elev}/{n} 地点。国土地理院の標高表示と照合：{checked} 地点中 {same} 地点で一致",
         "地理院タイルの標高タイル（1m→5m→10mメッシュ）。座標を直すと自動で計算し直し、古い値は使わない"),
        ("住所LOD", f"{loa}/{n} 地点の IRI が開けることを確認", "住所LODの階層をたどって照合（郡・大字・丁目の書き方の違いを合わせた）"),
        ("統計LOD（標準地域コード）", f"{sac}/{n} 地点", "統計LODの SPARQL で、市区町村コードの最新の項目を選んだ"),
        ("Wikidata", f"同じ施設 {same_wd} 件（{checked_wd} 施設を確認）、構成施設 {len({(r['id'], q) for r in rows for q in conv.split_qids(r.get('wikidata_related'))})} 件",
         "候補を1件ずつ開いて名前・場所・説明を確かめたものだけをつなぐ。同じ施設と構成施設に同じ項目を入れるとSHACLで止まる"),
        ("写真", f"{n_img} 枚（{len(imgs)} 施設）すべてに撮影者とライセンス", "撮影者かライセンスが欠けるとSHACLで止まる"),
        ("全体", f"{len(g)} トリプル", "VoID（void.ttl）にほかのデータとのつながりの数"),
    ]
    cc = ROOT / "data" / "wikidata_crosscheck.csv"
    if cc.exists():
        xs = conv.load_rows(str(cc))
        pts = [x for x in xs if x.get("facility_type") in ("ため池", "堰", "揚水機場") and x.get("distance_km")]
        near = [x for x in pts if float(x["distance_km"]) <= 1.0]
        cans = [float(x["distance_km"]) for x in xs if x.get("facility_type") not in ("ため池", "堰", "揚水機場") and x.get("distance_km")]
        yrs = [x for x in xs if x.get("our_built_year") and x.get("wd_inception_year")]
        same_y = [x for x in yrs if x["our_built_year"] == x["wd_inception_year"]]
        dec_y = [x for x in yrs if x not in same_y and x.get("wd_inception_precision") == "10年単位"
                 and int(x["our_built_year"]) // 10 == int(x["wd_inception_year"]) // 10]
        diff_y = [x for x in yrs if x not in same_y and x not in dec_y]
        when = max((x.get("retrieved", "") for x in xs), default="")
        checks.append(("Wikidata との突き合わせ（外部のデータとの照合）",
                       f"座標：点の施設（ため池・堰など）{len(near)}/{len(pts)} 件が Wikidata の座標から1km以内。"
                       f"水路は代表地点の選び方が違うため参考（{min(cans):.1f}〜{max(cans):.1f}km）。"
                       f"年：比べられる {len(yrs)} 件のうち一致 {len(same_y)}、10年単位で一致 {len(dec_y)}、差あり {len(diff_y)}"
                       + ("（" + "、".join(f"{x['id'].replace('WHIS-JP-', '')}：このデータ {x['our_built_year']}・Wikidata {x['wd_inception_year']}" for x in diff_y) + "）" if diff_y else "")
                       + f"（{when}）",
                       "「同じ施設」とした Wikidata 項目の座標（P625）と開始年（P571）を、このデータと自動で比べた（data/wikidata_crosscheck.csv）。年の差は、何の年（着工・完成など）を採ったかの違いもありうるので、このデータでは「建設年の根拠」欄に何の年かを書いている"))
    lr = ROOT / "docs" / "link_report.csv"
    if lr.exists():
        rep = conv.load_rows(str(lr))
        okn = sum(1 for x in rep if x.get("ok") == "1")
        bad = [x for x in rep if x.get("ok") != "1"]
        when = max((x.get("checked", "") for x in rep), default="")
        checks.append(("リンクの健康診断", f"{len(rep)} 件中 {okn} 件が開けた（{when}）" +
                       ("" if not bad else "。開けなかったもの：" + "、".join(f"{x['id']}（{x['status']}）" for x in bad[:10])),
                       "出典URL・外部リンク・写真・住所LODを毎月自動で確かめる（scripts/check_links.py）"))
    else:
        checks.append(("リンクの健康診断", "まだ実行していません",
                       "出典URL・外部リンク・写真・住所LODを毎月自動で確かめる（scripts/check_links.py）"))
    rows_html = "".join(f"<tr><th>{e(a)}</th><td>{e(b)}</td><td><small>{e(c)}</small></td></tr>" for a, b, c in checks)
    cols = [(k, lbl) for k, lbl in FIELD_LABELS if k not in ("note",)]
    prof = "".join(
        f"<tr><th>{e(lbl)}</th><td>{sum(1 for r in rows if (r.get(k) or '').strip())}/{n}</td></tr>" for k, lbl in cols)
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>検証レポート｜世界かんがい施設遺産（日本）LOD</title><style>{PAGE_CSS}</style></head><body>
<nav><a href="index.html">地図</a><a href="sparql.html">SPARQL</a><a href="watersystems.html">水系</a><a href="ontology.html">語彙</a><a href="en.html">English</a></nav>
<h1>検証レポート</h1>
<p>このデータに対して行っているチェックと、その結果です（{e(today)} に作成）。サイトを作り直すたびに自動で作り直されます。
同じ数値を、W3C の Data Quality Vocabulary（DQV）で機械が読める形にした <a href="quality.ttl">quality.ttl</a> もあります。</p>
<table><tr><th>項目</th><td><b>結果</b></td><td><b>確かめ方</b></td></tr>{rows_html}</table>
<h2>項目ごとの値がある施設の数</h2>
<p><small>出典に書かれていない値や、資料で値が違う値は空欄にしています（空欄＝不明。0ではありません）。</small></p>
<table>{prof}</table>
</body></html>
"""


def watersystem_page(rows, flow):
    """水系のページ：遺産の水源の川が、どの本流を通ってどの海（湖）へ注ぐかで遺産をまとめる。"""
    e = html.escape
    nxt = {f["from_qid"]: f["to_qid"] for f in flow}
    label = {}
    lab_csv = ROOT / "data" / "wikidata_labels.csv"
    if lab_csv.exists():
        for x in conv.load_rows(str(lab_csv)):
            label[x["qid"]] = x["label_ja"]
    for f in flow:
        label[f["from_qid"]] = f["from_label"]
        label[f["to_qid"]] = f["to_label"]
    groups, no_qid = {}, []
    for r in rows:
        qs = conv.split_qids(r.get("water_source_river_qid"))
        if not qs:
            no_qid.append(r)
            continue
        names = [n.strip() for n in (r.get("water_source_river") or "").replace("、", ";").split(";")]
        for i, q in enumerate(qs):
            chain, seen = [q], {q}
            while chain[-1] in nxt and nxt[chain[-1]] not in seen:
                seen.add(nxt[chain[-1]])
                chain.append(nxt[chain[-1]])
            term = chain[-1]
            lab = lambda x: label.get(x) or (names[i] if x == q and i < len(names) else x)
            path = " → ".join(e(lab(x)) for x in chain[:-1]) if len(chain) > 1 else ""
            groups.setdefault(term, []).append((path, r, lab(term)))
    sec = []
    for term, items in sorted(groups.items(), key=lambda kv: (-len({x[1]["id"] for x in kv[1]}), kv[1][0][2])):
        n = len({x[1]["id"] for x in items})
        tl = items[0][2]
        lis = "".join(
            f'<li><a href="resource/{e(r["id"])}.html">{e(r["name_ja"])}</a>'
            f'{"（" + path + " → " + e(tl) + "）" if path else "（" + e(tl) + "から直接）"}</li>'
            for path, r, _ in sorted(items, key=lambda x: x[0]))
        sec.append(f'<h2>{e(tl)}（{n}施設）</h2><ul>{lis}</ul>')
    rest = "、".join(f'<a href="resource/{e(r["id"])}.html">{e(r["name_ja"])}</a>' for r in no_qid)
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>水系でみる｜世界かんがい施設遺産（日本）LOD</title><style>{PAGE_CSS}</style></head><body>
<nav><a href="index.html">地図</a><a href="sparql.html">SPARQL</a><a href="quality.html">検証</a><a href="ontology.html">語彙</a><a href="en.html">English</a></nav>
<h1>水系でみる世界かんがい施設遺産</h1>
<p>遺産が水を引く川・湖を Wikidata の項目につなぎ、Wikidata の「河口・流出先」（P403）をたどって、どの本流を通ってどの海・湖へ注ぐかでまとめました。
同じ海・本流にまとまる遺産は、同じ水系の水を分け合っています。<small>（川の流れのつながりは Wikidata（CC0）から {e(flow[0]["retrieved"]) if flow else ""} に写したもの。data/river_flow.csv。）</small></p>
{"".join(sec)}
<h2>水源の川・湖が Wikidata の項目につながっていない施設（{len(no_qid)}施設）</h2>
<p><small>湧水・地下水、小さな川など、Wikidata に項目が見つからなかったもの。</small><br>{rest}</p>
</body></html>
"""


def quality_ttl(rows, base, terrain, addr, imgs, today):
    """検証レポートの数値を、W3C の Data Quality Vocabulary（DQV）で機械が読める形にする（quality.ttl）。"""
    from rdflib import Graph, Literal, Namespace, URIRef, RDF
    from rdflib.namespace import XSD, SKOS, DCTERMS
    DQV = Namespace("http://www.w3.org/ns/dqv#")
    W = Namespace(base + "ontology#")
    q = Graph()
    q.bind("dqv", DQV); q.bind("skos", SKOS); q.bind("dcterms", DCTERMS); q.bind("whis", W)
    ds = URIRef(base + "dataset")
    n = len(rows)

    def measure(key, label, definition, value, dim):
        m = W["metric-" + key]
        q.add((m, RDF.type, DQV.Metric))
        q.add((m, SKOS.prefLabel, Literal(label, lang="ja")))
        q.add((m, SKOS.definition, Literal(definition, lang="ja")))
        q.add((m, DQV.expectedDataType, XSD.decimal))
        q.add((m, DQV.inDimension, W["dimension-" + dim]))
        qm = URIRef(base + f"quality.ttl#{key}")
        q.add((qm, RDF.type, DQV.QualityMeasurement))
        q.add((qm, DQV.computedOn, ds))
        q.add((qm, DQV.isMeasurementOf, m))
        q.add((qm, DQV.value, Literal(f"{value:.4f}", datatype=XSD.decimal)))
        q.add((qm, DCTERMS.date, Literal(today, datatype=XSD.date)))
        q.add((ds, DQV.hasQualityMeasurement, qm))

    for dim, lab in [("completeness", "完全性"), ("accuracy", "正確さ"), ("provenance", "来歴"), ("linkability", "つながり")]:
        d = W["dimension-" + dim]
        q.add((d, RDF.type, DQV.Dimension)); q.add((d, SKOS.prefLabel, Literal(lab, lang="ja")))
    measure("source-coverage", "出典のある施設の割合", "出典URLが1つ以上ある施設の数÷施設の数",
            sum(1 for r in rows if conv.split_urls(r.get("source_url"))) / n, "provenance")
    for col, lab in [("lat", "座標"), ("built_year", "建設年"), ("irrigated_area_ha", "かんがい面積"),
                     ("managing_org", "管理者"), ("name_en", "英語名")]:
        measure(f"completeness-{col}", f"{lab}がある施設の割合", f"{lab}の値がある施設の数÷施設の数（空欄は不明の意味）",
                sum(1 for r in rows if (r.get(col) or "").strip()) / n, "completeness")
    ts = [current_terrain(r, terrain.get(r["id"])) for r in rows]
    chk = [t for t in ts if t.get("gsi_elevation_api_m")]
    if chk:
        from decimal import Decimal, ROUND_HALF_UP
        mesh = {"DEM1A": "1m", "DEM5A": "5m", "DEM5B": "5m", "DEM5C": "5m", "DEM10B": "10m"}
        ok = 0
        for t in chk:
            m_ = mesh.get(t.get("elevation_dem"), "")
            qq = Decimal("1") if m_ == "10m" else Decimal("0.1")
            ok += (Decimal(t["elevation_m"]).quantize(qq, ROUND_HALF_UP) == Decimal(t["gsi_elevation_api_m"]).quantize(qq, ROUND_HALF_UP)
                   and t.get("gsi_elevation_api_mesh") == m_)
        measure("elevation-agreement", "標高が国土地理院の標高表示と一致した割合",
                "国土地理院の標高APIの値（同じ単位に丸める）と、使った標高モデルの種類が一致した地点の数÷照合した地点の数", ok / len(chk), "accuracy")
    cc = ROOT / "data" / "wikidata_crosscheck.csv"
    if cc.exists():
        xs = [x for x in conv.load_rows(str(cc)) if x.get("facility_type") in ("ため池", "堰", "揚水機場") and x.get("distance_km")]
        if xs:
            measure("wikidata-point-agreement", "点の施設の座標が Wikidata と1km以内の割合",
                    "ため池・堰・揚水機場で、Wikidata の座標（P625）から1km以内にある施設の数÷比べた施設の数",
                    sum(1 for x in xs if float(x["distance_km"]) <= 1) / len(xs), "accuracy")
    measure("address-link-coverage", "住所LODにつないだ代表地点の割合", "住所LODの IRI がある施設の数÷施設の数",
            sum(1 for r in rows if (addr.get(r["id"]) or [{}])[0].get("loa_uri")) / n, "linkability")
    measure("wikidata-same-coverage", "Wikidata と「同じ施設」でつないだ施設の割合", "owl:sameAs がある施設の数÷施設の数",
            sum(1 for r in rows if r.get("verified") == "1" and r.get("wikidata_qid")) / n, "linkability")
    lr = ROOT / "docs" / "link_report.csv"
    if lr.exists():
        rep = conv.load_rows(str(lr))
        if rep:
            measure("link-health", "開けたリンクの割合", "毎月のリンク健康診断で開けたURLの数÷確かめたURLの数",
                    sum(1 for x in rep if x.get("ok") == "1") / len(rep), "accuracy")
    return q.serialize(format="turtle")

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--creator", default="【氏名またはハンドルネーム】")
    ap.add_argument("--modified", default="2026-12-31")
    ap.add_argument("--csv", default=str(ROOT / "data" / "whis_japan.csv"))
    ap.add_argument("--prefqid", default=str(ROOT / "data" / "prefecture_qid.csv"))
    ap.add_argument("--docs", default=str(ROOT / "docs"))
    ap.add_argument("--images", default=str(ROOT / "data" / "images.csv"))
    ap.add_argument("--extlinks", default=str(ROOT / "data" / "external_links.csv"))
    ap.add_argument("--terrain", default=str(ROOT / "data" / "point_terrain.csv"))
    ap.add_argument("--addrlinks", default=str(ROOT / "data" / "address_links.csv"))
    ap.add_argument("--riverflow", default=str(ROOT / "data" / "river_flow.csv"))
    a = ap.parse_args(argv)
    base = a.base.rstrip("/") + "/"
    docs = Path(a.docs)
    (docs / "resource").mkdir(parents=True, exist_ok=True)

    rc = conv.main(["--csv", a.csv, "--base", base, "--prefqid", a.prefqid,
                    "--out-ttl", str(docs / "whis_japan.ttl"), "--out-geojson", str(docs / "whis_japan.geojson"),
                    "--creator", a.creator, "--modified", a.modified,
                    "--images", a.images, "--extlinks", a.extlinks, "--terrain", a.terrain, "--addrlinks", a.addrlinks,
                    "--riverflow", a.riverflow, "--wdlabels", str(ROOT / "data" / "wikidata_labels.csv")])
    from rdflib import Graph, URIRef
    g = Graph().parse(docs / "whis_japan.ttl", format="turtle")
    (docs / "whis_japan.jsonld").write_text(g.serialize(format="json-ld", indent=1), encoding="utf-8")
    (docs / "whis_japan.nt").write_text(g.serialize(format="nt"), encoding="utf-8")   # 1行1トリプル（大量処理・差分比較向け）
    shutil.copyfile(a.csv, docs / "whis_japan.csv")
    images = conv.load_optional_csv(a.images)
    exts = conv.load_optional_csv(a.extlinks)
    terrain = conv.load_optional_csv(a.terrain)
    addr = conv.load_optional_csv(a.addrlinks)
    flow = conv.load_rows(a.riverflow)
    for src in [a.images, a.extlinks, a.terrain, a.addrlinks, a.riverflow, str(ROOT / "data" / "wikidata_labels.csv")]:
        if Path(src).exists():
            shutil.copyfile(src, docs / Path(src).name)
    # 地図の部品（背景の切り替え・昔の航空写真の重ね合わせ）
    shutil.copyfile(ROOT / "templates" / "gsi_layers.js", docs / "gsi_layers.js")
    (docs / "void.ttl").write_text(void_ttl(g, base), encoding="utf-8")
    shapes = ROOT / "shapes" / "whis_shapes.ttl"
    if shapes.exists():
        (docs / "shapes.ttl").write_text(
            shapes.read_text(encoding="utf-8").replace("REPLACE_BASE", base.rstrip("/")), encoding="utf-8")

    with open(a.csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        (docs / "resource" / f"{r['id']}.html").write_text(
            resource_page(r, base, a.creator, images.get(r["id"]), exts.get(r["id"]), terrain.get(r["id"]), addr.get(r["id"])),
            encoding="utf-8")
        # 施設ごとの機械可読ファイル（その施設を主語とする三つ組と、座標のノード）
        s = URIRef(base + "resource/" + r["id"])
        sub = Graph()
        for pfx, ns in g.namespaces():
            sub.bind(pfx, ns)
        for t in g.triples((s, None, None)):
            sub.add(t)
        for t in g.triples((URIRef(str(s) + "/geometry"), None, None)):
            sub.add(t)
        for _, _, img in g.triples((s, URIRef("https://schema.org/image"), None)):
            for t in g.triples((img, None, None)):
                sub.add(t)
        (docs / "resource" / f"{r['id']}.ttl").write_text(sub.serialize(format="turtle"), encoding="utf-8")
        (docs / "resource" / f"{r['id']}.jsonld").write_text(sub.serialize(format="json-ld", indent=1), encoding="utf-8")
    (docs / "ontology.html").write_text(ontology_page(base), encoding="utf-8")
    (docs / "en.html").write_text(english_page(rows, base, terrain, images), encoding="utf-8")
    (docs / "watersystems.html").write_text(watersystem_page(rows, flow), encoding="utf-8")
    (docs / "quality.ttl").write_text(quality_ttl(rows, base, terrain, addr, images, a.modified), encoding="utf-8")
    (docs / "quality.html").write_text(quality_page(rows, base, terrain, addr, images, g, a.modified), encoding="utf-8")
    print(f"施設ページ {len(rows)} 件（HTML・Turtle・JSON-LD）、ontology.html、JSON-LD、CSV を {docs} に出力しました")
    return rc


if __name__ == "__main__":
    sys.exit(main())
