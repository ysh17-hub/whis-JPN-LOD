#!/usr/bin/env python3
"""Turtle を読み込んで、サンプル SPARQL（Q1〜Q3）をローカルで実行する確認用スクリプト。
使い方: python run_queries.py --ttl ../data/whis_japan.ttl --base https://YOUR_GITHUB_NAME.github.io/whis-lod/
"""
import argparse
from rdflib import Graph


def queries(base):
    base = base.rstrip("/") + "/"
    pre = f"""
PREFIX whis: <{base}ontology#>
PREFIX schema: <https://schema.org/>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""
    return {
        "Q1 都道府県ごとの登録数": pre + """
SELECT ?pref (COUNT(?s) AS ?n) WHERE {
  ?s a whis:HeritageIrrigationStructure ; schema:addressRegion ?pref .
} GROUP BY ?pref ORDER BY DESC(?n) ?pref""",
        "Q2 登録年ごとの件数": pre + """
SELECT ?year (COUNT(?s) AS ?n) WHERE {
  ?s a whis:HeritageIrrigationStructure ; whis:registeredYear ?year .
} GROUP BY ?year ORDER BY ?year""",
        "Q4 同じ川から水を引く遺産（川でつながる施設）": pre + """
SELECT ?river (COUNT(?s) AS ?n) (GROUP_CONCAT(?name; separator="、") AS ?names) WHERE {
  ?s a whis:HeritageIrrigationStructure ; whis:waterSource ?river ; schema:name ?name .
  FILTER(LANG(?name) = "ja")
} GROUP BY ?river HAVING (COUNT(?s) >= 2) ORDER BY DESC(?n)""",
        "Q5 建設年が古い順（上位10件・根拠つき）": pre + """
SELECT ?by ?name ?basis WHERE {
  ?s a whis:HeritageIrrigationStructure ; whis:builtYear ?by ; schema:name ?name .
  OPTIONAL { ?s whis:builtYearBasis ?basis }
  FILTER(LANG(?name) = "ja")
} ORDER BY ?by LIMIT 10""",
        "Q6 建設から登録までの年数（長い順・上位10件）": pre + """
SELECT ?name ?by ?ry ((xsd:integer(STR(?ry)) - xsd:integer(STR(?by))) AS ?span) WHERE {
  ?s a whis:HeritageIrrigationStructure ; whis:builtYear ?by ; whis:registeredYear ?ry ; schema:name ?name .
  FILTER(LANG(?name) = "ja")
} ORDER BY DESC(?span) LIMIT 10""",
        "Q7 施設の種類ごとの件数": pre + """
SELECT ?type (COUNT(?s) AS ?n) WHERE {
  ?s a whis:HeritageIrrigationStructure ; whis:facilityType ?type .
} GROUP BY ?type ORDER BY DESC(?n)""",
        "Q3 座標もWikidataリンクも無い施設の数": pre + """
SELECT (COUNT(?s) AS ?n) WHERE {
  ?s a whis:HeritageIrrigationStructure .
  FILTER NOT EXISTS { ?s geo:hasGeometry ?g }
  FILTER NOT EXISTS { ?s owl:sameAs ?wd }
}""",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ttl", required=True)
    ap.add_argument("--base", required=True)
    a = ap.parse_args()
    g = Graph().parse(a.ttl, format="turtle")
    for title, q in queries(a.base).items():
        print("==", title)
        for row in g.query(q):
            print("  ", " | ".join(str(x) for x in row))


if __name__ == "__main__":
    main()
