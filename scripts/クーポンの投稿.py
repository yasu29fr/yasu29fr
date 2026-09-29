"""楽天トラベルの大きいクーポン（40%OFF以上）を紹介する投稿を、明日ぶんに1本だけ足す

2026-09-30 代表指示：
  「40％以上の割引がある場合は、そのホテルの紹介投稿をする」
  「部屋限定の情報は本文の注釈に。見出しには入れなくてよい」
参考にした形（代表が共有した投稿）：
  1本目 … 「〇〇を考えてる人へ／ホテル名が、期間限定で◯%OFFです…！」
  返信  … 「【期間限定◯%OFF🔥】対象はこちら👇 リンク PR」

クーポンは x-yu__fukui-bot の neta/宿_大きいクーポン.jsonl（週1回更新）を読む。
同じクーポンは1回だけ。同じ宿は14日あける。1日1本まで。文面はテンプレートで組み立てる（AI に書かせない）。

環境変数:
  COUPON_HOUR  … 何時に出すか（yu は 19、福井は 18）
  COUPON_STYLE … yu / fukui（書きぶり）
  TARGET_DATE  … 対象日（無ければ明日）
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
QUEUE = Path("posts/queue.jsonl")
元 = ("https://api.github.com/repos/yasu29fr/x-yu__fukui-bot/contents/neta/"
      "%E5%AE%BF_%E5%A4%A7%E3%81%8D%E3%81%84%E3%82%AF%E3%83%BC%E3%83%9D%E3%83%B3.jsonl")
印 = "大きいクーポン："


def 行を読む(文: str) -> list[dict]:
    出 = []
    for l in 文.splitlines():
        l = l.strip()
        if l.startswith("{"):
            try:
                出.append(json.loads(l))
            except json.JSONDecodeError:
                pass
    return 出


def クーポンを読む() -> list[dict]:
    # 別リポジトリの公開ファイル。トークン付きで断られたら、トークン無しで読み直す
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    for つける in ([True, False] if tok else [False]):
        req = urllib.request.Request(元, headers={"Accept": "application/vnd.github.raw"})
        if つける:
            req.add_header("Authorization", f"Bearer {tok}")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return 行を読む(r.read().decode("utf-8"))
        except Exception as e:
            print(f"::warning::大きいクーポンが読めません（{'トークンあり' if つける else 'トークンなし'}・{e}）")
    return []


def これまでの投稿() -> list[dict]:
    出 = {e.get("id"): e for e in 行を読む(QUEUE.read_text(encoding="utf-8"))}
    try:
        hs = subprocess.run(["git", "log", "--since=30 days ago", "--format=%H", "--", str(QUEUE)],
                            capture_output=True, text=True, timeout=60).stdout.split()
        for h in hs:
            t = subprocess.run(["git", "show", f"{h}:{QUEUE}"], capture_output=True, text=True).stdout
            for e in 行を読む(t):
                出.setdefault(e.get("id"), e)
    except Exception:
        pass
    return list(出.values())


def 本文(宿: list[dict], style: str) -> str:
    最大 = max(int(x["率"]) for x in 宿)
    名 = 宿[0]["宿名"]
    注 = []
    for x in sorted(宿, key=lambda x: -int(x["率"])):
        項 = f"{x['率']}%OFF：{x.get('対象') or '対象の部屋・プラン'}"
        if x.get("先着"):
            項 += f"（先着{x['先着']}枚）"
        注.append(項)
    使えない = next((x.get("使えない日") for x in 宿 if x.get("使えない日")), "")
    注文 = "※" + "／".join(注) + (f"。{使えない}は使えません" if 使えない else "")
    if style == "yu":
        頭 = f"福井で泊まる予定がある人へ🏯\n{名}が、\n期間限定で{'最大' if len(宿) > 1 else ''}{最大}%OFFです…！"
    else:
        頭 = f"{名}に、楽天トラベルで{'最大' if len(宿) > 1 else ''}{最大}%OFFのクーポンが出ています。\n\n福井で泊まる予定がある人へ。"
    文 = f"{頭}\n\n{注文}"
    if len(文) > 480:
        文 = 文[:477] + "…"
    return 文


def 返信(宿: list[dict], style: str) -> str:
    最大 = max(int(x["率"]) for x in 宿)
    期 = max(str(x.get("宿泊の最終日") or "") for x in 宿)
    期文 = f"（{int(期[5:7])}/{int(期[8:10])}の宿泊まで）" if len(期) == 10 else ""
    if style == "yu":
        return f"【期間限定{最大}%OFF🔥】{期文}\n対象の部屋・プランはこちら👇\n{宿[0]['リンク']}\n\nPR"
    return f"期間限定{最大}%OFF{期文}\n対象の部屋・プランはこちら\n{宿[0]['リンク']}\n\nPR"


def main() -> None:
    hour = int(os.environ.get("COUPON_HOUR") or 19)
    style = os.environ.get("COUPON_STYLE", "yu").strip()
    指定 = os.environ.get("TARGET_DATE", "").strip()
    日 = datetime.strptime(指定, "%Y-%m-%d").date() if 指定 else (datetime.now(JST) + timedelta(days=1)).date()
    at = f"{日.isoformat()}T{hour:02d}:00:00+09:00"
    if datetime.fromisoformat(at) <= datetime.now(JST):
        print("出す時刻を過ぎています。何もしません。")
        return
    過去 = これまでの投稿()
    if any(str(e.get("scheduled_at")) == at for e in 過去):
        print(f"{at} はもう埋まっています。何もしません。")
        return
    if any(印 in str(e.get("note", "")) and str(e.get("scheduled_at", ""))[:10] == 日.isoformat() for e in 過去):
        print("この日はもう大きいクーポンの投稿があります（1日1本まで）。")
        return
    使った鍵, 最近の宿 = set(), set()
    for e in 過去:
        n = str(e.get("note", ""))
        if 印 in n:
            for 鍵 in n.split(印, 1)[1].split("／")[0].split(","):
                使った鍵.add(鍵.strip())
            try:
                d = datetime.strptime(str(e.get("scheduled_at"))[:10], "%Y-%m-%d").date()
                if (日 - d).days < 14:
                    最近の宿.add(n.split(印, 1)[1].split(":")[0])
            except ValueError:
                pass
    宿ごと: dict[str, list[dict]] = {}
    for x in クーポンを読む():
        if x.get("鍵") in 使った鍵 or str(x.get("宿番号")) in 最近の宿:
            continue
        if str(x.get("獲得期限") or "9999") < 日.isoformat() or str(x.get("宿泊の最終日") or "9999") <= 日.isoformat():
            continue
        宿ごと.setdefault(str(x.get("宿番号")), []).append(x)
    if not 宿ごと:
        print("出せる大きいクーポンはありません。")
        return
    宿 = max(宿ごと.values(), key=lambda v: max(int(x["率"]) for x in v))
    item = {
        "id": f"p-coupon-{日:%m%d}-{hour:02d}",
        "text": 本文(宿, style),
        "scheduled_at": at,
        "thread": [返信(宿, style)],
        "note": f"{印}{','.join(x['鍵'] for x in 宿)}／楽天トラベル（PR）。クーポンページで確かめた内容をテンプレートで組み立て（2026-09-30 代表指示）",
    }
    lines = QUEUE.read_text(encoding="utf-8")
    前 = len(lines.splitlines())
    if lines and not lines.endswith("\n"):
        lines += "\n"
    QUEUE.write_text(lines + json.dumps(item, ensure_ascii=False) + "\n", encoding="utf-8")
    assert len(QUEUE.read_text(encoding="utf-8").splitlines()) == 前 + 1
    print(f"::warning::大きいクーポンの投稿を {at} に入れました：{宿[0]['宿名']}（最大{max(int(x['率']) for x in 宿)}%OFF）")
    print(item["text"]); print("---"); print(item["thread"][0])


if __name__ == "__main__":
    main()
