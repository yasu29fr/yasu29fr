"""運営事業部・数字の担当 — アフィリエイト枠の成績（サイクルの⑥分析・⑦改善）

2026-09-27 代表指示：
  「投稿ごとでなくていい。アカウントごと・投稿ごとの表示回数と、
    全体のクリック合計で、ある程度予想はできる」

やること
  1. 3アカウント（yu・福井・X）の queue と metrics を読み、投稿ごとの最新の表示回数を並べる
  2. 投稿を「美容／楽天トラベル／ふるさと納税／その他の楽天／ふつう」に分ける
  3. 代表が伝えたクリック合計（neta/クリック.jsonl）を、同じ期間の表示回数で割って
     クリック率を推定し、投稿ごとの「推定クリック」を出す
  4. insights/アフィリの成績.md（人が読む）と insights/アフィリの学び.json（次の投稿が読む）を書く

クリックはリンク単位では取れない（楽天のレポートはショップ別・日別まで）。
だから「その分類の表示回数 × その分類のクリック率」で見積もる。あくまで目安。
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
アカウント = {
    # 名前: (リポジトリ, ブランチ)。3つとも公開リポジトリ
    "yu": ("yu-fukui/threads_yu-fukui", "main"),
    "福井": ("fukui-fukui/threads", "main"),
    "X": ("yu-fukui/x-yu__fukui-bot", "main"),
}
クリックの置き場 = Path("neta/クリック.jsonl")
成績の置き場 = Path("insights/アフィリの成績.md")
学びの置き場 = Path("insights/アフィリの学び.json")
見る日数 = 14


def 取ってくる(名: str, repo: str, branch: str) -> Path:
    """公開リポジトリを浅く clone する（直近 見る日数+5 日ぶんの履歴つき）。"""
    先 = Path(tempfile.gettempdir()) / f"affi-{名}"
    if 先.exists():
        subprocess.run(["git", "-C", str(先), "fetch", "-q", "origin", branch], check=False)
        subprocess.run(["git", "-C", str(先), "reset", "-q", "--hard", "FETCH_HEAD"], check=False)
        return 先
    subprocess.run(["git", "clone", "-q", "--single-branch", "-b", branch,
                    f"--shallow-since={見る日数 + 5} days ago",
                    f"https://github.com/{repo}.git", str(先)], check=True)
    return 先


def 行を読む(文: str) -> list[dict]:
    出 = []
    for l in 文.splitlines():
        l = l.strip()
        if l and not l.startswith("#"):
            try:
                出.append(json.loads(l))
            except json.JSONDecodeError:
                pass
    return 出


def 過去のqueue(先: Path) -> dict[str, dict]:
    """queue の過去の版を全部読み、id ごとに最後に見えた中身を返す。

    福井の queue は投稿済みの行が消えていくので、今の queue だけでは
    何の投稿だったか（note・本文）が分からない（2026-09-27 確認）。
    """
    ハッシュ = subprocess.run(
        ["git", "-C", str(先), "log", "--reverse", "--format=%H", "--", "posts/queue.jsonl"],
        capture_output=True, text=True).stdout.split()
    出: dict[str, dict] = {}
    for h in ハッシュ:
        r = subprocess.run(["git", "-C", str(先), "show", f"{h}:posts/queue.jsonl"],
                           capture_output=True, text=True)
        for e in 行を読む(r.stdout):
            if e.get("id"):
                出[e["id"]] = e
    now = 先 / "posts/queue.jsonl"
    if now.exists():
        for e in 行を読む(now.read_text(encoding="utf-8")):
            if e.get("id"):
                出[e["id"]] = e
    return 出


def 分ける(id_: str, note: str, text: str, thread: list[str]) -> str:
    if id_.startswith("p-beauty-") or note.startswith("運営事業部・美容"):
        return "美容"
    if "ふるさと納税" in note or "ふるさと納税" in text:
        return "ふるさと納税"
    if "楽天トラベル" in note or "楽天トラベル" in text:
        return "楽天トラベル"
    if any("a.r10.to" in t or "hb.afl.rakuten" in t for t in thread):
        return "その他の楽天"
    return "ふつう"


def 美容の中身(note: str) -> tuple[str, str]:
    部 = note.split("／")
    商品 = 部[1] if len(部) > 1 else ""
    m = re.search(r"切り口：([^／]+)", note)
    return 商品, (m.group(1) if m else "")


def トラベルの切り口(note: str) -> str:
    m = re.search(r"切り口[＝=]([^、，,／]+)", note)
    if m:
        return m.group(1).strip()
    if "クーポン" in note:
        return "クーポン（5と0のつく日）"
    return "?"


def 投稿を集める(今日: datetime) -> list[dict]:
    出 = []
    for 名, (repo, branch) in アカウント.items():
        try:
            先 = 取ってくる(名, repo, branch)
        except subprocess.CalledProcessError as e:  # 1つ読めなくても、読める分で出す
            print(f"::warning::{repo} を取れません（{e}）")
            continue
        queue = 過去のqueue(先)
        m = 先 / "insights/metrics.jsonl"
        最新: dict[str, dict] = {}
        for r in 行を読む(m.read_text(encoding="utf-8") if m.exists() else ""):
            if r.get("id"):
                最新[r["id"]] = r  # 同じ投稿を毎日測るので、最後の行が最新
        for id_, r in 最新.items():
            try:
                日 = datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=JST)
            except (KeyError, ValueError):
                continue
            if (今日 - 日).days > 見る日数:
                continue
            e = queue.get(id_, {})
            note = e.get("note") or r.get("note") or ""
            text = e.get("text") or ""
            thread = e.get("thread") or []
            分類 = 分ける(id_, note, text, thread)
            x = {"アカウント": 名, "id": id_, "日": r["date"], "時": int(r.get("hour", 0)),
                 "表示": int(r.get("views", 0)), "いいね": int(r.get("likes", 0)),
                 "分類": 分類, "1行目": (text.splitlines() or [r.get("first_line", "")])[0][:40],
                 "本文": text, "返信": thread[-1] if thread else ""}
            if 分類 == "美容":
                x["商品"], x["切り口"] = 美容の中身(note)
            if 分類 == "楽天トラベル":
                x["切り口"] = トラベルの切り口(note)
                if x["切り口"] == "?":
                    x["切り口"] = "（1行目）" + x["1行目"][:20]
            出.append(x)
    return 出


def クリックを読む() -> list[dict]:
    """1行 = 代表が伝えた1回ぶん。
    {"始め": "2026-09-27", "終わり": "2026-09-27", "楽天トラベル": 12, "美容": 3, "ふるさと納税": 2, "その他": 0}
    分けられないときは「その他」にまとめてよい（楽天トラベル以外の全部として扱う）。"""
    if not クリックの置き場.exists():
        return []
    return [json.loads(l) for l in クリックの置き場.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.lstrip().startswith("#")]


# クリックの欄 → どの分類の表示で割るか
欄の分類 = {
    "楽天トラベル": {"楽天トラベル"},
    "美容": {"美容"},
    "ふるさと納税": {"ふるさと納税"},
}
アフィリの分類 = {"美容", "楽天トラベル", "ふるさと納税", "その他の楽天"}


def クリック率を出す(投稿: list[dict], クリック: list[dict]) -> dict[str, dict]:
    合計 = defaultdict(lambda: {"クリック": 0, "表示": 0})
    # 表示の記録（直近 見る日数）より前から始まる期間は使わない。
    # 分母の表示が欠けて、クリック率が大きく出すぎる（9/1〜9/25 の累計で 18% と出た。2026-09-27）
    最古 = (datetime.now(JST) - timedelta(days=見る日数)).strftime("%Y-%m-%d")
    for c in クリック:
        始め, 終わり = c["始め"], c["終わり"]
        if 始め < 最古:
            print(f"::notice::クリック {始め}〜{終わり} は表示の記録より前から始まるので使いません")
            continue
        期間 = [p for p in 投稿 if 始め <= p["日"] <= 終わり]
        使った: set[str] = set()
        for 欄, 分類 in 欄の分類.items():
            if 欄 in c:
                使った |= 分類
                合計[欄]["クリック"] += int(c[欄])
                合計[欄]["表示"] += sum(p["表示"] for p in 期間 if p["分類"] in 分類)
        if "その他" in c:
            残り = アフィリの分類 - 使った
            合計["その他"]["クリック"] += int(c["その他"])
            合計["その他"]["表示"] += sum(p["表示"] for p in 期間 if p["分類"] in 残り)
            合計["その他"]["中身"] = "・".join(sorted(残り))
    for v in 合計.values():
        v["率"] = v["クリック"] / v["表示"] if v["表示"] else None
    return dict(合計)


def 率を引く(率: dict, 分類: str) -> float | None:
    if 分類 in 率 and 率[分類]["率"] is not None:
        return 率[分類]["率"]
    if "その他" in 率 and 分類 in 率["その他"].get("中身", "") and 率["その他"]["率"] is not None:
        return 率["その他"]["率"]
    return None


def 平均(xs):
    return round(statistics.mean(xs)) if xs else 0


def main() -> None:
    今日 = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    投稿 = 投稿を集める(今日)
    クリック = クリックを読む()
    率 = クリック率を出す(投稿, クリック)
    for p in 投稿:
        r = 率を引く(率, p["分類"])
        p["推定クリック"] = round(p["表示"] * r, 1) if r is not None and p["分類"] in アフィリの分類 else None

    書 = [f"# アフィリエイト枠の成績（{今日:%Y-%m-%d} 更新・直近{見る日数}日）", "",
         "数字の担当が毎日つくる表です。表示は投稿ごとの実数、クリックは代表が伝えた合計からの**推定**です。", ""]

    # 1. アカウントごと
    書 += ["## 1. アカウントごと", "", "| アカウント | 投稿 | 合計表示 | 平均表示 | うちアフィリ枠 | アフィリ枠の平均表示 |", "|---|---|---|---|---|---|"]
    for 名 in アカウント:
        全 = [p for p in 投稿 if p["アカウント"] == 名]
        ア = [p for p in 全 if p["分類"] in アフィリの分類]
        書.append(f"| {名} | {len(全)} | {sum(p['表示'] for p in 全):,} | {平均([p['表示'] for p in 全]):,} | {len(ア)} | {平均([p['表示'] for p in ア]):,} |")
    書.append("")

    # 2. クリック率
    書 += ["## 2. クリックとクリック率（推定）", ""]
    if not 率:
        書 += ["まだクリックの記録がありません。代表からチャットで「9/27 トラベル12 その他5」のように伝えてもらい、",
              "`neta/クリック.jsonl` に書き足します。", ""]
    else:
        書 += ["| 欄 | クリック | 同じ期間の表示 | クリック率 |", "|---|---|---|---|"]
        for 欄, v in 率.items():
            r = f"{v['率'] * 100:.2f}%" if v["率"] is not None else "—"
            書.append(f"| {欄}{'（' + v['中身'] + '）' if v.get('中身') else ''} | {v['クリック']} | {v['表示']:,} | {r} |")
        書.append("")

    # 3. 美容
    美 = sorted([p for p in 投稿 if p["分類"] == "美容"], key=lambda p: (p["日"], p["時"]))
    書 += ["## 3. 美容（yu）", ""]
    if not 美:
        書 += ["まだ測れた投稿がありません（投稿から24時間後に測ります）。", ""]
    else:
        書 += ["| 日 | 時 | 商品 | 切り口 | 表示 | いいね | 推定クリック | 1行目 |", "|---|---|---|---|---|---|---|---|"]
        for p in 美:
            書.append(f"| {p['日'][5:]} | {p['時']} | {p['商品'][:16]} | {p['切り口'][:22]} | {p['表示']:,} | {p['いいね']} | {p['推定クリック'] if p['推定クリック'] is not None else '—'} | {p['1行目'][:24]} |")
        書 += ["", "**商品ごと**", "", "| 商品 | 本数 | 平均表示 |", "|---|---|---|"]
        g = defaultdict(list)
        for p in 美:
            g[p["商品"]].append(p["表示"])
        for k, v in sorted(g.items(), key=lambda kv: -平均(kv[1])):
            書.append(f"| {k} | {len(v)} | {平均(v):,} |")
        書 += ["", "**時刻ごと**", "", "| 時 | 本数 | 平均表示 |", "|---|---|---|"]
        g = defaultdict(list)
        for p in 美:
            g[p["時"]].append(p["表示"])
        for k in sorted(g):
            書.append(f"| {k}時 | {len(g[k])} | {平均(g[k]):,} |")
        書.append("")

    # 4. 楽天トラベル
    旅 = sorted([p for p in 投稿 if p["分類"] == "楽天トラベル"], key=lambda p: (p["日"], p["アカウント"]))
    書 += ["## 4. 楽天トラベル（15時・3アカウント）", ""]
    if not 旅:
        書 += ["まだ測れた投稿がありません。", ""]
    else:
        書 += ["| 日 | 切り口 | アカウント | 表示 | 推定クリック |", "|---|---|---|---|---|"]
        for p in 旅:
            書.append(f"| {p['日'][5:]} | {p['切り口'][:24]} | {p['アカウント']} | {p['表示']:,} | {p['推定クリック'] if p['推定クリック'] is not None else '—'} |")
        g = defaultdict(list)
        for p in 旅:
            g[p["切り口"]].append(p["表示"])
        書 += ["", "**切り口ごと（3アカウントの合計）**", "", "| 切り口 | 本数 | 合計表示 |", "|---|---|---|"]
        for k, v in sorted(g.items(), key=lambda kv: -sum(kv[1])):
            書.append(f"| {k[:28]} | {len(v)} | {sum(v):,} |")
        書.append("")

    # 5. ⑦ 次の投稿へ返すこと
    学び: dict = {"更新": f"{今日:%Y-%m-%d}", "美容_伸びた": [], "美容_伸びなかった": []}
    書 += ["## 5. 次の投稿へ返すこと（⑦改善）", ""]
    if len(美) >= 4:
        並 = sorted(美, key=lambda p: -p["表示"])
        学び["美容_伸びた"] = [{k: p[k] for k in ("日", "時", "商品", "切り口", "表示", "本文")} for p in 並[:2]]
        学び["美容_伸びなかった"] = [{k: p[k] for k in ("日", "時", "商品", "切り口", "表示", "本文")} for p in 並[-1:]]
        書 += [f"- 美容の投稿ライターに、表示が多かった2本（{並[0]['表示']:,}・{並[1]['表示']:,}）の書き出しを見本として渡す",
              f"- 表示が少なかった1本（{並[-1]['表示']:,}）の書き出しは避けるよう渡す"]
    else:
        書 += [f"- 美容は測れた投稿が {len(美)} 本。4本たまるまでは見本を変えない"]
    書.append("")

    成績の置き場.parent.mkdir(exist_ok=True)
    成績の置き場.write_text("\n".join(書) + "\n", encoding="utf-8")
    学びの置き場.write_text(json.dumps(学び, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("\n".join(書))


if __name__ == "__main__":
    main()
