# 世界かんがい施設遺産（日本）Linked Open Data

**World Heritage Irrigation Structures in Japan as Linked Open Data**

日本の「世界かんがい施設遺産」60施設（2014〜2026年登録）を、**出典付きの Linked Open Data**（RDF / JSON-LD / GeoJSON / CSV）にしたデータセットと地図です。

- 地図：https://ysh17-hub.github.io/whis-lod/
- データ：[`docs/whis_japan.ttl`](docs/whis_japan.ttl)（Turtle）／[`docs/whis_japan.jsonld`](docs/whis_japan.jsonld)／[`docs/whis_japan.geojson`](docs/whis_japan.geojson)／[`data/whis_japan.csv`](data/whis_japan.csv)
- ライセンス：データは **CC BY 4.0**、プログラムは **MIT**（[LICENSE](LICENSE)）

---

## なぜ作ったか

世界かんがい施設遺産は、国際かんがい排水委員会（ICID）が、建設から100年以上たった歴史的なかんがい施設を認定・登録する制度です（2014年創設）。日本は登録数が世界最多で、2025年時点で世界200施設のうち56施設が日本にあります（農林水産省 2026年8月21日発表の参考資料3）。2026年には4施設が加わり、60施設になりました。

しかし、施設の情報は農林水産省・各地方農政局・自治体・土地改良区のページやPDFに分かれていて、**機械で読める形の一覧、座標、他のデータへのリンクはありません**。農林水産省の手引きも、世界かんがい施設遺産は世間の認知度が低いとしています（https://www.maff.go.jp/j/nousin/kantai/giahs_7/attach/pdf/index-8.pdf ）。

このデータセットは、散らばった公的資料を **1施設ずつ出典を付けて** 構造化し、地図と URI で「見つけられる・つなげられる」形にしたものです。

## 中身

| 項目 | 入っている件数（60施設中） | 説明 |
|---|---|---|
| 名称・都道府県・市町村・登録年 | 60 | 農林水産省の登録施設一覧と、2026年8月21日の認定発表による |
| 施設の種類 | 60 | 水路・用水群・ため池・堰・揚水機場（農水省の対象施設区分に合わせた） |
| 水源 | 45 | 川・湖・湧水・地下水 |
| 代表地点の名前 | 60 | 座標を取る場所（取水口・堰・池・水門など） |
| 建設年と、その根拠 | 39 | 着工・完成・供用開始のどれかを `built_year_basis` に必ず書いた |
| 管理者 | 34 | 土地改良区など |
| 英語名 | 20 | 農林水産省の施設概要PDFにある英語名 |
| かんがい面積 | 19 | 資料で値が異なるものは空欄にし、注記に両方を書いた |
| 緯度・経度 | 60 | 代表地点の座標（下の「座標の決め方」） |
| Wikidata へのリンク | 21 | 同じものと確認できたものだけ `owl:sameAs`。確認した 60 施設のうち、**Wikidata に対応する項目がなかった施設は 39 件** |
| 出典URL | 全行 | 1行に複数可（縦棒で区切る）。全体で 72 の資料を参照 |

### データでわかること（例）

- **利根川は4つの遺産の水源**：見沼代用水・天狗岩用水・備前渠用水路・葛西用水（`whis:waterSource` でつながる。SPARQL の Q4）。
- **建設年が分かる施設で最も古いのは満濃池**（大宝年間 701〜704年築造、821年に空海が修築）。ただし、狭山池（約1,400年前）のように年が一つに決まらない施設は建設年を空欄にしているため、この順位は「年が確定できる施設の中で」の話です。
- 都道府県別では静岡県が7施設で最多（2026年の小笠地域かんがい用水群を含む）。

## データモデル

既存の語彙を優先し、足りない項目だけ独自語彙 `whis:` を定義しました（[語彙の説明](docs/ontology.html)）。

| 内容 | 使った語彙 |
|---|---|
| 施設の型 | `whis:HeritageIrrigationStructure`（`schema:LandmarksOrHistoricalBuildings` のサブクラス） |
| 名称 | `schema:name`, `rdfs:label`（日本語・英語の言語タグ付き） |
| 所在地 | `schema:addressRegion`, `schema:addressLocality`, `whis:prefectureCode`（ISO 3166-2:JP）, `schema:containedInPlace`（都道府県の Wikidata） |
| 座標 | GeoSPARQL（`geo:hasGeometry` / `geo:asWKT`）と W3C Basic Geo（`wgs84:lat` / `wgs84:long`）の両方 |
| 年 | `whis:registeredYear`, `whis:builtYear`（`xsd:gYear`）, `whis:builtYearBasis` |
| 出典・注記 | `dcterms:source`, `rdfs:comment` |
| 外部リンク | `owl:sameAs`（Wikidata。確認済みのみ） |
| データセット | DCAT（`dcat:Dataset`）、`dcterms:license`, `dcterms:creator`, `dcterms:modified` |

各施設の URI（例：`https://ysh17-hub.github.io/whis-lod/resource/WHIS-JP-026`）をブラウザで開くと、その施設のページ（schema.org の JSON-LD を埋め込み）が表示されます。

### SPARQL の例

`scripts/run_queries.py` で、次の問い合わせをローカルで実行できます（rdflib）。

- Q1 都道府県ごとの登録数　／　Q2 登録年ごとの件数
- Q4 同じ川から水を引く遺産　／　Q5 建設年が古い順　／　Q6 建設から登録までの年数
- Q7 施設の種類ごとの件数　／　Q3 座標も Wikidata リンクもない施設（作業の残り）

```
pip install rdflib
python scripts/run_queries.py --ttl docs/whis_japan.ttl --base https://ysh17-hub.github.io/whis-lod/
```

## データの作り方と品質の方針

1. **数値は出典に書かれた範囲だけ**を入れました。「約400年前」のように年が一つに決まらないものは `built_year` を空欄にし、注記に原文の表現を残しました。
2. **資料によって値が違うもの**（例：稲生川のかんがい面積 5,900ha と 5,200ha、入鹿池の 600ha と 1,300ha）は、どちらかを選ばず空欄にし、注記に両方と出典を書きました。
3. 名称は認定時の正式名称にそろえました（例：2026年4月の申請時は「日根荘のかんがい用水群」、8月の認定時は「日根荘大木のかんがい用水群」）。
4. 変換スクリプトは、**登録基準（建設から100年以上）と矛盾する建設年**、根拠のない建設年、座標の範囲外などを自動で検出します。
5. 座標は施設の範囲（水路の全長など）ではなく、**代表地点の1点**です。代表地点（`representative_point`、取水口・堰・池など）を、国土地理院の航空写真（地理院タイル）で目で確かめ、座標入力ツール（`tools/pick_coords.html`）で1点ずつ入力しました。Wikidata の座標を使った場合も、航空写真で位置を確かめてから採用しています。
6. Wikidata との同一関係（`owl:sameAs`）は、候補を一つずつ開いて同じ施設だと確かめたもの（`verified=1`）だけに付けました。

## 毎年の更新手順

新しい施設が登録されたら：

1. `data/whis_japan.csv` に1行足す（ID は続き番号、出典URLを必ず入れる）
2. `tools/pick_coords.html` をブラウザで開いて座標を入れ、保存したCSVを `python lod.py import` で取り込む
3. `python lod.py build`（docs/ と README を作り直す）
4. GitHub に上げる（GitHub Pages に反映されます）

## ファイル構成

```
lod.py                     作業用のコマンド（setup / wikidata / import / build / status）
data/whis_japan.csv        元データ（これだけを編集する）
docs/                      GitHub Pages で公開するもの（build_site.py が作る）
  index.html               地図（登録年のスライダー、再生、水源での絞り込み）
  resource/*.html          施設ごとのページ（JSON-LD 付き）
  ontology.html            独自語彙の説明
  whis_japan.ttl / .jsonld / .geojson / .csv
scripts/
  csv_to_rdf.py            CSV → RDF / GeoJSON（検証つき）
  build_site.py            docs/ を一式つくる
  fetch_wikidata.py        都道府県の QID と、施設の Wikidata 候補を集める
  run_queries.py           SPARQL の例
queries/sample_queries.rq  SPARQL の例（Wikidata 側で実行する例を含む）
tools/pick_coords.html     座標を確かめて入力するためのツール（航空写真・Wikidata候補の表示）
templates/                 README・LICENSE のひな形（lod.py build が README.md と LICENSE を作る）
```

## 出典と利用条件

- 主な出典：農林水産省「世界かんがい施設遺産 登録施設の概要」（https://www.maff.go.jp/j/nousin/kaigai/ICID/his/abstruct.html ）と各施設の概要PDF、農林水産省プレスリリース「令和8年度世界かんがい施設遺産の認定について」（2026年8月21日）、各地方農政局・都道府県・市・土地改良区の公開資料。施設ごとの出典は各行の `source_url` を見てください。
- 各レコードには、出典の資料から名称・年・面積などの**事実だけ**を取り出して記録し、資料の文章・図・写真は転載していません。
- 農林水産省ウェブサイトのコンテンツは、出典を記載し、編集・加工した場合はその旨を記載すれば利用できます（農林水産省「利用ルール」https://www.maff.go.jp/j/use/link.html ）。このデータセットは、農林水産省などの資料をもとに作成者が編集・加工して作成したもので、国や自治体が作成したものではありません。
- 地図の背景：地理院タイル（国土地理院）。地理院タイルをリアルタイムで読み込んで表示するウェブサイトは、出典の明示のみで申請不要とされています（国土地理院 https://www.gsi.go.jp/LAW/2930-qa.html ）。
- Wikidata のデータは CC0 です。

## 作成者

abe（業）


データの数値は、出典の資料で確認しています。

（最終更新：2026-11-23）

---

### English summary

This repository publishes the 60 World Heritage Irrigation Structures (WHIS) registered in Japan by ICID between 2014 and 2026 as Linked Open Data (Turtle, JSON-LD, GeoJSON and CSV), with a source URL for every record. It reuses schema.org, GeoSPARQL, W3C Basic Geo, DCMI Terms and DCAT, and defines a small `whis:` vocabulary only where needed (registration year, built year and its basis, facility type, water source, irrigated area). Values that differ between official sources are left blank and both values are recorded in a comment. Links to Wikidata (`owl:sameAs`) are added only after manual verification. Data: CC BY 4.0. Code: MIT.
