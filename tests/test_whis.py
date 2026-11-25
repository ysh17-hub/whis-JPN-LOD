"""whis-lod の自動テスト。

使い方（リポジトリのいちばん上のフォルダで）：
    python lod.py build                      # 先にサイトを作る
    python -m unittest discover -s tests -v

GitHub Actions でも、build のあとにこのテストを実行し、通らなければ公開しない。
"""
import csv
import json
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT / "scripts"))

import csv_to_rdf as conv  # noqa: E402


def load_rows():
    with open(ROOT / "data" / "whis_japan.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def site_base():
    cfg = json.loads((ROOT / "site_config.json").read_text(encoding="utf-8"))
    return cfg.get("uri_base") or f"https://{cfg['github_user'].lower()}.github.io/{cfg['repo']}/"


def built():
    return (DOCS / "whis_japan.ttl").exists() and (DOCS / "resource").is_dir()


class TestData(unittest.TestCase):
    """元データ（data/whis_japan.csv）が、README に書いた決まりを守っているか。"""

    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()

    def test_validate_has_no_problems(self):
        # 年が一つに決まらない値を建設年に入れない、何の年かを必ず書く、などの決まり（csv_to_rdf.validate）
        self.assertEqual(conv.validate(conv.load_rows(str(ROOT / "data" / "whis_japan.csv"))), [])

    def test_ids_are_unique_and_well_formed(self):
        ids = [r["id"] for r in self.rows]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertRegex(i, r"^WHIS-JP-\d{3}$")

    def test_no_column_is_entirely_empty(self):
        for col in self.rows[0]:
            with self.subTest(column=col):
                self.assertTrue(any((r.get(col) or "").strip() for r in self.rows), f"{col} の列がすべて空です")

    def test_every_row_has_a_source_url(self):
        for r in self.rows:
            with self.subTest(id=r["id"]):
                urls = [u.strip() for u in re.split(r"\s*\|\s*", r["source_url"]) if u.strip()]
                self.assertTrue(urls)
                for u in urls:
                    self.assertRegex(u, r"^https?://")

    def test_built_year_rules(self):
        for r in self.rows:
            by, basis, period = r["built_year"].strip(), r["built_year_basis"].strip(), r["built_period"].strip()
            with self.subTest(id=r["id"]):
                if by:
                    self.assertRegex(by, r"^\d{3,4}$")
                    self.assertTrue(basis, "建設年には、何の年かを書く")
                    self.assertFalse(period, "建設年があるときは建設時期を使わない")
                else:
                    self.assertFalse(basis, "建設年がないのに、何の年かが書いてある")

    def test_english_names_are_latin(self):
        for r in self.rows:
            with self.subTest(id=r["id"]):
                self.assertTrue(all(32 <= ord(ch) < 127 for ch in r["name_en"]), r["name_en"])

    def test_numbers_are_numbers(self):
        for r in self.rows:
            with self.subTest(id=r["id"]):
                if r["irrigated_area_ha"].strip():
                    self.assertRegex(r["irrigated_area_ha"].strip(), r"^\d+(\.\d+)?$")
                if r["lat"].strip():
                    self.assertTrue(20 <= float(r["lat"]) <= 46 and 122 <= float(r["lon"]) <= 154)


@unittest.skipUnless(built(), "先に python lod.py build を実行してください")
class TestSite(unittest.TestCase):
    """作ったサイト（docs/）が壊れていないか。"""

    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()
        cls.base = site_base()

    def test_shacl_conforms(self):
        import pyshacl
        from rdflib import Graph
        data = Graph().parse(DOCS / "whis_japan.ttl", format="turtle")
        shapes = Graph().parse(DOCS / "shapes.ttl", format="turtle")
        conforms, _, text = pyshacl.validate(data, shacl_graph=shapes, inference="none")
        self.assertTrue(conforms, text)

    def test_every_facility_has_page_and_rdf(self):
        from rdflib import Graph, URIRef
        for r in self.rows:
            with self.subTest(id=r["id"]):
                for ext in ("html", "ttl", "jsonld"):
                    self.assertTrue((DOCS / "resource" / f"{r['id']}.{ext}").exists(), ext)
                g = Graph().parse(DOCS / "resource" / f"{r['id']}.ttl", format="turtle")
                self.assertIn(URIRef(self.base + "resource/" + r["id"]), set(g.subjects()))
                json.loads((DOCS / "resource" / f"{r['id']}.jsonld").read_text(encoding="utf-8"))

    def test_outputs_are_in_stable_order(self):
        # 同じデータからは同じファイルになるように、N-Triples は行の順、JSON-LD は中身の順に並べて書く
        lines = (DOCS / "whis_japan.nt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, sorted(set(lines)))
        import build_site
        for p in [DOCS / "whis_japan.jsonld", DOCS / "resource" / f"{self.rows[0]['id']}.jsonld"]:
            with self.subTest(file=p.name):
                from rdflib import Graph
                text = p.read_text(encoding="utf-8")
                again = build_site.stable_jsonld(Graph().parse(data=text, format="json-ld"))
                self.assertEqual(json.loads(text), json.loads(again))

    def test_no_broken_internal_links(self):
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.found = []

            def handle_starttag(self, tag, attrs):
                for k, v in attrs:
                    if k in ("href", "src") and v:
                        self.found.append(v)

        pages = sorted(DOCS.glob("*.html")) + sorted((DOCS / "resource").glob("*.html"))
        broken = []
        for page in pages:
            p = Links()
            p.feed(page.read_text(encoding="utf-8"))
            for link in p.found:
                if link.startswith(self.base):
                    target = DOCS / unquote(urlsplit(link).path[len(urlsplit(self.base).path):])
                elif re.match(r"^(https?:|mailto:|data:|javascript:|#|//)", link) or "${" in link:
                    continue
                else:
                    target = (page.parent / unquote(urlsplit(link).path)).resolve()
                if target.is_dir():
                    target = target / "index.html"
                if not (target.exists() or target.with_suffix(target.suffix + ".html").exists()
                        or Path(str(target) + ".html").exists()):
                    broken.append(f"{page.relative_to(DOCS)} → {link}")
        self.assertEqual(broken, [])

    def test_scripts_and_styles_are_served_with_the_site(self):
        # 地図などのライブラリを外部の配信サイトから読み込まない（配信サイトが止まっても表示できるように）
        pat = re.compile(r'<(?:script[^>]+src|link[^>]+rel="stylesheet"[^>]+href)="(https?://[^"]+)"')
        for page in sorted(DOCS.glob("*.html")) + sorted((DOCS / "resource").glob("*.html")):
            with self.subTest(page=page.name):
                self.assertEqual(pat.findall(page.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
