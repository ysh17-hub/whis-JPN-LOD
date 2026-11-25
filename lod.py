#!/usr/bin/env python3
"""
世界かんがい施設遺産LOD の作業用コマンド（Windows / Mac 共通）

  python lod.py setup      … 最初に1回。GitHubのユーザー名・作成者名などを聞いて site_config.json に保存
  python lod.py wikidata   … Wikidata から都道府県のIDと、施設の候補を集める（5〜15分）
  python lod.py import     … 座標入力ツールで保存したCSV（ダウンロードフォルダ）を取り込む
  python lod.py build      … 検証して、docs/（公開用サイト）と README.md・LICENSE を作る
  python lod.py status     … 進み具合（座標・Wikidataの確認が何件終わったか）を表示

※ Windows では「python」の代わりに「py」と打ってください（例：py lod.py setup）。
"""
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True          # __pycache__ を作らない（GitHubに上げるときに邪魔になるため）
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
DATA = ROOT / "data" / "whis_japan.csv"
CONFIG = ROOT / "site_config.json"
BACKUP_DIR = ROOT.parent / (ROOT.name + "_backup")   # リポジトリの外に置く（GitHubに上げないため）


# ---------- 共通 ----------
def ask(prompt, default=""):
    shown = f"{prompt}" + (f"［そのままEnterで {default}］" if default else "") + "：\n> "
    v = input(shown).strip()
    return v or default


def load_config(required=True):
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    if required:
        print("先に「setup」を実行してください（Windows: py lod.py setup ／ Mac: python3 lod.py setup）")
        sys.exit(1)
    return {}


def base_url(cfg):
    """施設などの URI の土台。site_config.json に "uri_base"（例：https://w3id.org/whis-lod/）があればそれを使う。
    w3id.org の転送が動き出してから設定する（転送が動く前に変えると、URI が開けなくなる）。"""
    return cfg.get("uri_base") or f"https://{cfg['github_user'].lower()}.github.io/{cfg['repo']}/"


def repo_url(cfg):
    return f"https://github.com/{cfg['github_user']}/{cfg['repo']}"


def read_rows(path=DATA):
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def counts(rows):
    filled = lambda k: sum(1 for r in rows if (r.get(k) or "").strip())
    years = sorted((int(r["built_year"]), r["name_ja"]) for r in rows if (r.get("built_year") or "").strip().isdigit())
    c = {
        "OLDEST_YEAR": years[0][0] if years else "",
        "OLDEST_NAME": years[0][1] if years else "",
        "N_ROWS": len(rows),
        "N_COORDS": sum(1 for r in rows if r.get("lat") and r.get("lon")),
        "N_VERIFIED": sum(1 for r in rows if r.get("verified") == "1" and r.get("wikidata_qid")),
        "N_CHECKED": sum(1 for r in rows if r.get("wikidata_checked") == "1" or r.get("verified") == "1"),
    }
    c["N_NO_WD"] = sum(1 for r in rows if r.get("wikidata_checked") == "1" and r.get("verified") != "1")
    c["N_RELATED"] = sum(1 for r in rows if (r.get("wikidata_related") or "").strip())
    c["N_RIVER_QID"] = sum(1 for r in rows if (r.get("water_source_river_qid") or "").strip())
    c["N_RIVER_DISTINCT"] = len({q.strip() for r in rows for q in (r.get("water_source_river_qid") or "").split(";") if q.strip()})
    for k in ["facility_type", "water_source_river", "representative_point", "built_year", "built_period",
              "managing_org", "name_en", "irrigated_area_ha", "point_address"]:
        c["N_" + k] = filled(k)
    c["N_BUILT_ANY"] = sum(1 for r in rows if (r.get("built_year") or r.get("built_period") or "").strip())
    c["N_SOURCES"] = len({u.strip() for r in rows for u in (r.get("source_url") or "").split("|") if u.strip()})
    # 写真と外部データベース（data/images.csv・data/external_links.csv。なければ 0）
    imgs, exts = [], []
    if (ROOT / "data" / "images.csv").exists():
        _, imgs = read_rows(ROOT / "data" / "images.csv")
    if (ROOT / "data" / "external_links.csv").exists():
        _, exts = read_rows(ROOT / "data" / "external_links.csv")
    c["N_PHOTO"] = len(imgs)
    c["N_PHOTO_FAC"] = len({r["id"] for r in imgs})
    c["N_EXT"] = len(exts)
    c["N_EXT_FAC"] = len({r["id"] for r in exts})
    c["N_SEEALSO_FAC"] = len({r["id"] for r in exts if r.get("relation") == "same"})
    c["N_EXT_SOURCES"] = len({r["source"] for r in exts})
    # 代表地点の標高・昔の空中写真（data/point_terrain.csv）
    ter = []
    if (ROOT / "data" / "point_terrain.csv").exists():
        _, ter = read_rows(ROOT / "data" / "point_terrain.csv")
    c["N_ELEV"] = sum(1 for r in ter if r.get("elevation_m"))
    adr = []
    if (ROOT / "data" / "address_links.csv").exists():
        _, adr = read_rows(ROOT / "data" / "address_links.csv")
    c["N_LOA"] = sum(1 for r in adr if r.get("loa_uri"))
    c["N_LOA_TOWN"] = sum(1 for r in adr if r.get("loa_uri") and r.get("loa_level") != "市区町村")
    c["N_SAC"] = sum(1 for r in adr if r.get("sac_uri"))
    c["N_SAC_DISTINCT"] = len({r["sac_uri"] for r in adr if r.get("sac_uri")})
    for k, col in [("N_AIR1945", "aerial_1945_1950"), ("N_AIR1961", "aerial_1961_1969"), ("N_AIR1974", "aerial_1974_1978")]:
        c[k] = sum(1 for r in ter if r.get(col) == "1")
    # 標高を、地理院地図の標高表示（標高API）と照合した結果。API は 1m・5m メッシュを 0.1m、10m メッシュを 1m 単位で返すので、同じ単位に丸めて比べる
    from decimal import Decimal, ROUND_HALF_UP
    mesh = {"DEM1A": "1m", "DEM5A": "5m", "DEM5B": "5m", "DEM5C": "5m", "DEM10B": "10m"}
    checked = [r for r in ter if r.get("gsi_elevation_api_m")]
    same = 0
    for r in checked:
        m = mesh.get(r.get("elevation_dem"), "")
        q = Decimal("1") if m == "10m" else Decimal("0.1")
        v = Decimal(r["elevation_m"]).quantize(q, rounding=ROUND_HALF_UP)
        same += (v == Decimal(r["gsi_elevation_api_m"]).quantize(q, rounding=ROUND_HALF_UP) and r.get("gsi_elevation_api_mesh") == m)
    retrieved = max((r.get("retrieved", "") for r in checked), default="")
    c["ELEV_CHECK"] = (f"{len(checked)}地点中{same}地点で、使われた標高モデルの種類と値（APIの単位に丸めた値）が一致。{retrieved}照合"
                       if checked else "未照合")
    return c


# ---------- 版（同じ入力からは同じ出力にする） ----------
# データや作り方そのもの（作ったサイトではなく、元になるファイル）
SOURCE_PATHS = ["data", "scripts", "templates", "shapes", "lod.py", "site_config.json", "CHANGELOG.md",
                "requirements.txt", "docs/index.html", "docs/sparql.html", "docs/gsi_layers.js", "docs/vendor"]


def source_version():
    """データの日付と、元になったコミットを返す。
    ビルドした日ではなく「データや作り方を最後に変えた日」を使うので、同じ入力から何度作っても同じ出力になる。
    git の記録がなければ CHANGELOG.md のいちばん上の日付を使う。環境変数 WHIS_DATA_DATE があればそれを優先。"""
    d, sha = os.environ.get("WHIS_DATA_DATE", "").strip(), ""
    if not d:
        try:
            out = subprocess.run(["git", "log", "-1", "--format=%cs %H", "--", *SOURCE_PATHS], cwd=ROOT,
                                 capture_output=True, text=True, timeout=30).stdout.split()
            if len(out) == 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", out[0]):
                d, sha = out
        except (OSError, subprocess.SubprocessError):
            pass
    if not d:
        ch = ROOT / "CHANGELOG.md"
        m = re.search(r"^## (\d{4}-\d{2}-\d{2})", ch.read_text(encoding="utf-8"), re.M) if ch.exists() else None
        d = m.group(1) if m else dt.date.today().isoformat()
    return d, sha


# ---------- setup ----------
def cmd_setup():
    cfg = load_config(required=False)
    print("=== 最初の設定（あとで「setup」をもう一度実行すれば変えられます）===\n")
    print("GitHub のユーザー名を入れてください（github.com/○○○ の ○○○ の部分。公開URLになります）")
    cfg["github_user"] = ask("GitHubのユーザー名", cfg.get("github_user", ""))
    while not cfg["github_user"] or any(ch in cfg["github_user"] for ch in " /\\@"):
        print("※ 空白・/・@ は使えません。GitHub に表示されているユーザー名をそのまま入れてください")
        cfg["github_user"] = ask("GitHubのユーザー名")
    cfg["repo"] = ask("リポジトリの名前", cfg.get("repo", "whis-lod"))
    print("\n作成者として公開する名前（本名でもハンドルネームでもよい。README・データ・LICENSEに載ります）")
    cfg["creator"] = ask("作成者名", cfg.get("creator", ""))
    while not cfg["creator"]:
        cfg["creator"] = ask("作成者名（空にはできません）")
    print("\n所属（READMEに載せる場合だけ。載せないならそのままEnter）")
    cfg["affiliation"] = ask("所属", cfg.get("affiliation", ""))
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存しました → {CONFIG.name}")
    print(f"公開URL（予定）：{base_url(cfg)}")
    print(f"リポジトリURL（予定）：{repo_url(cfg)}")


# ---------- wikidata ----------
def cmd_wikidata():
    cfg = load_config()
    try:
        import fetch_wikidata
    except ImportError:
        print("requests が入っていません。次を実行してから、もう一度どうぞ：")
        print("  Windows: py -m pip install requests rdflib\n  Mac:     python3 -m pip install requests rdflib")
        sys.exit(1)
    print("Wikidata に問い合わせます（相手のサーバーに負担をかけないよう間隔をあけるので、5〜15分かかります）\n")
    fetch_wikidata.main(["--csv", str(DATA), "--outdir", str(ROOT / "data"), "--contact", repo_url(cfg)])
    print("\nできたファイル：data/prefecture_qid.csv、data/wikidata_candidates.csv")
    print("次は tools/pick_coords.html をブラウザで開いて、座標と Wikidata の確認をします。")


# ---------- import ----------
def cmd_import():
    downloads = Path.home() / "Downloads"
    cands = sorted(downloads.glob("whis_japan*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not cands:
        print(f"{downloads} に whis_japan で始まるCSVが見つかりません。")
        print("座標入力ツールで「CSVを保存」を押したか、保存先がダウンロードフォルダか確認してください。")
        sys.exit(1)
    new = cands[0]
    h_new, r_new = read_rows(new)
    h_old, r_old = read_rows()
    print(f"取り込むファイル：{new}（{dt.datetime.fromtimestamp(new.stat().st_mtime):%Y-%m-%d %H:%M} 保存）")
    ids_old = [r["id"] for r in r_old]
    ids_new = [r["id"] for r in r_new]
    if ids_new != ids_old:
        print("※ 施設のIDの並びが今のデータと違います。別のファイルの可能性があるので取り込みを中止しました。")
        sys.exit(1)
    missing = [h for h in h_old if h not in h_new]
    if missing:
        print(f"※ 列が足りません：{missing}。取り込みを中止しました。")
        sys.exit(1)
    c_old, c_new = counts(r_old), counts(r_new)
    changed = sum(1 for a, b in zip(r_old, r_new) if any(a.get(k, "") != b.get(k, "") for k in h_new))
    # 大事な列の変更を1件ずつ見せる（古いファイルや自動保存で、確認済みのデータが戻ってしまうのを防ぐ）
    watch = ["lat", "lon", "wikidata_qid", "wikidata_related", "water_source_river_qid", "verified"]
    erased = 0
    for a, b in zip(r_old, r_new):
        for k in watch:
            va, vb = a.get(k, ""), b.get(k, "")
            if k in h_new and va != vb:
                mark = ""
                if va and not vb:
                    mark = "  ← 値が消えます"
                    erased += 1
                print(f"  {a['id']} {a['name_ja']}｜{k}：{va or '（空）'} → {vb or '（空）'}{mark}")
    if erased:
        print(f"※ 今のデータにある値が {erased} か所で空になります。古いファイルや自動保存を読み込んでいないか確認してください。")
    print(f"変更のある行：{changed} 行")
    print(f"座標あり：{c_old['N_COORDS']} → {c_new['N_COORDS']} ／ Wikidata確認済み：{c_old['N_CHECKED']} → {c_new['N_CHECKED']}")
    if ask("取り込みますか？（y / n）", "y").lower() != "y":
        print("中止しました")
        return
    BACKUP_DIR.mkdir(exist_ok=True)
    bk = BACKUP_DIR / f"whis_japan_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
    shutil.copyfile(DATA, bk)
    shutil.copyfile(new, DATA)
    print(f"取り込みました。前のデータは {bk} に保存しました。")
    print("次は「build」でサイトを作り直します。")


# ---------- build ----------
def run_shacl(docs, today):
    """docs/whis_japan.ttl が shapes の形に合っているかを pyshacl で確かめる。入っていなければ飛ばす。"""
    try:
        import pyshacl
    except ImportError:
        print("（pyshacl が入っていないので、SHACL のチェックは飛ばしました。入れるなら: python3 -m pip install pyshacl）")
        return None
    from rdflib import Graph
    if not (docs / "shapes.ttl").exists():
        return None
    data = Graph().parse(docs / "whis_japan.ttl", format="turtle")
    shapes = Graph().parse(docs / "shapes.ttl", format="turtle")
    conforms, _, text = pyshacl.validate(data, shacl_graph=shapes, inference="none")
    (docs / "shacl_report.txt").write_text(
        f"SHACL validation ({today})\nshapes: shapes.ttl\ndata: whis_japan.ttl\nconforms: {conforms}\n\n{text}",
        encoding="utf-8")
    print(f"SHACL のチェック：{'合格（形の誤りなし）' if conforms else '不合格'} → docs/shacl_report.txt")
    if not conforms:
        print(text)
    return conforms


def fill(template, values):
    s = template
    for k, v in values.items():
        s = s.replace(f"%%{k}%%", str(v))
    return s


def cmd_build():
    cfg = load_config()
    try:
        import rdflib  # noqa: F401
    except ImportError:
        print("rdflib が入っていません。次を実行してから、もう一度どうぞ：")
        print("  Windows: py -m pip install rdflib requests\n  Mac:     python3 -m pip install rdflib requests")
        sys.exit(1)
    import build_site
    import csv_to_rdf
    _, rows = read_rows()
    problems = csv_to_rdf.validate(rows)
    if problems:
        print("データに問題があります（直してから、もう一度 build してください）：")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    today, src_sha = source_version()   # ビルドした日ではなく、データを最後に変えた日
    if src_sha:
        os.environ["WHIS_SOURCE_COMMIT"] = src_sha
    print(f"データの日付：{today}" + (f"（コミット {src_sha[:7]}）" if src_sha else ""))
    # 代表地点の標高・昔の空中写真：まだ値のない施設と、座標を直した施設だけ地理院タイルから計算する
    import terrain
    try:
        n = terrain.update(str(DATA), str(ROOT / "data" / "point_terrain.csv"), log=print)
        if n:
            print(f"標高・空中写真：{n} 施設を新しく計算しました（data/point_terrain.csv）")
    except Exception as e:  # ネットにつながらないときなど。前の値のまま進める
        print(f"（標高・空中写真の計算はできませんでした：{e}。前の値を使います）")
    build_site.main(["--base", base_url(cfg), "--creator", cfg["creator"], "--modified", today,
                     "--csv", str(DATA), "--prefqid", str(ROOT / "data" / "prefecture_qid.csv"),
                     "--docs", str(ROOT / "docs")])
    conforms = run_shacl(ROOT / "docs", today)
    q = ROOT / "docs" / "quality.html"
    if q.exists():
        q.write_text(q.read_text(encoding="utf-8").replace(
            "%%SHACL_RESULT%%", {True: "合格（形の誤りなし）", False: "不合格", None: "未実施（pyshacl なし）"}[conforms]), encoding="utf-8")
    if conforms is False:
        print("SHACL のチェックで誤りが見つかりました。直してから、もう一度 build してください。")
        sys.exit(1)
    c = counts(rows)
    values = dict(c, BASE=base_url(cfg), SHACL=("合格" if conforms else "未実施"), REPO_URL=repo_url(cfg), CREATOR=cfg["creator"], TODAY=today,
                  YEAR=today[:4],
                  CREATOR_LINE=cfg["creator"] + (f"（{cfg['affiliation']}）" if cfg.get("affiliation") else ""))
    for name in ["README.md", "LICENSE"]:
        t = (ROOT / "templates" / f"{name}.tmpl").read_text(encoding="utf-8")
        text = fill(t, values)
        if name == "README.md":
            text = protect_urls(text)
        (ROOT / name).write_text(text, encoding="utf-8")
    print(f"\nREADME.md と LICENSE を作りました（作成者：{cfg['creator']}）")
    print(f"座標あり {c['N_COORDS']}/{c['N_ROWS']}、Wikidata 確認 {c['N_CHECKED']}/{c['N_ROWS']}"
          f"（対応あり {c['N_VERIFIED']}、なし {c['N_NO_WD']}、構成施設のリンクあり {c['N_RELATED']}）")
    print(f"水源を Wikidata につないだ施設 {c['N_RIVER_QID']}（川・湖 {c['N_RIVER_DISTINCT']} 件）")
    print(f"写真 {c['N_PHOTO']} 枚（{c['N_PHOTO_FAC']} 施設）、外部データベース・記事へのリンク {c['N_EXT']} 件（{c['N_EXT_FAC']} 施設）")
    print("\n公開後に開いて確認するURL：")
    b = base_url(cfg)
    for u in [b, b + "resource/WHIS-JP-026", b + "whis_japan.ttl", b + "sparql.html", b + "ontology.html", repo_url(cfg)]:
        print("  ", u)


def protect_urls(text):
    """GitHub は URL のすぐ後ろに日本語が続くと、その日本語までリンクに含めてしまう（例：「…/whis-lod/（背景…」）。
    そういう URL を <URL> で囲み、リンクが日本語の手前で終わるようにする。"""
    import re

    def fix(m):
        url = m.group(0)
        cut = re.search(r"[^\x00-\x7f]", url)
        if not cut:
            return url
        head, tail = url[:cut.start()], url[cut.start():]
        return f"<{head}>{tail}"
    return re.sub(r"(?<![(\[<`])https?://[^\s<>\]\)`]+", fix, text)


# ---------- status ----------
def cmd_status():
    _, rows = read_rows()
    c = counts(rows)
    print(f"座標あり：{c['N_COORDS']}/{c['N_ROWS']}　Wikidata確認：{c['N_CHECKED']}/{c['N_ROWS']}"
          f"（対応あり {c['N_VERIFIED']}、対応なし {c['N_NO_WD']}）")
    todo = [r for r in rows if not (r.get("lat") and r.get("lon"))]
    if todo:
        print("\n座標がまだの施設：")
        for r in todo:
            print(f"  {r['id']} {r['name_ja']}（{r['prefecture']}{r['municipality']}）代表地点：{r.get('representative_point') or '未設定'}")
    unchecked = [r for r in rows if r.get("wikidata_checked") != "1" and r.get("verified") != "1"]
    if unchecked:
        print(f"\nWikidata の確認がまだ：{len(unchecked)} 件")


def main():
    cmds = {"setup": cmd_setup, "wikidata": cmd_wikidata, "import": cmd_import, "build": cmd_build, "status": cmd_status}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]]()


if __name__ == "__main__":
    main()
