"""運営事業部・yuアカウント — 美容の投稿を作って queue に入れる

手順書: SNS運用サポート会社/部署/07_運営事業部/yuアカウント/

呼ばれ方は2つ。
  1. 代表が候補から1つ選んで短縮リンクを渡したとき（PICK と LINK が来る）
  2. 毎日 1:00（JST）。代表の返信が無く、次の日の美容の枠が空いていたら
     **自動で第一候補を選んで進める**（2026-09-26 代表指示「期限は翌日1:00」）

どちらも同じ手順を踏む。
  商品ページで事実を確かめる → レビューを読む → 切り口5つ → 投稿5本
  → 機械で薬機法の見張り → 07/13/20/22 に予約、残り1本は予備

**リンクは AI に書かせない。** 本文は LINK という目印で作らせ、最後にこちらで差し込む。
代表の短縮リンクが無いときは、楽天の商品検索APIが返したアフィリエイトURL（長い形）を使う。
どちらも同じアフィリエイトIDなので、成果は同じように付く。
"""

from __future__ import annotations


import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
QUEUE_PATH = Path("posts/queue.jsonl")
予備の置き場 = Path("neta/美容_予備.jsonl")
ログの置き場 = Path("neta/美容_決定ログ.jsonl")
候補のURL = (
    "https://raw.githubusercontent.com/yasu29fr/x-yu__fukui-bot/main/neta/"
    "%E7%BE%8E%E5%AE%B9%E5%80%99%E8%A3%9C.jsonl"
)
API = "https://api.anthropic.com/v1/messages"
枠 = ["07:00", "13:00", "20:00", "22:00"]

# 自動で選ぶときの決まり（代表が選ぶときは使わない）
自動の上限価格 = 30000          # これより高いものは Threads の流れで買われにくい
自動で避ける語 = ("脱毛器", "脱毛", "永久")  # 家庭用脱毛器は「永久脱毛」と書けず、書ける幅が狭い
同じ商品を空ける日数 = 14

# 薬機法の見張り（投稿ライターの手順書と同じ中身）
いつでも駄目 = ["消え", "薄くな", "治る", "治り", "治す", "改善", "効く", "効き目", "万能", "最強",
             "No.1", "NO.1", "ナンバーワン", "一番", "絶対", "必ず", "誰でも", "毛穴", "くすみ",
             "たるみ", "エイジング", "敏感肌でも", "永久", "若返", "痩せ",
             "リフトアップ", "小顔", "引き上げ", "肌質改善", "アンチエイジング"]
化粧品なら駄目 = ["防ぐ", "美白", "シミ", "しみ", "ニキビ", "にきび", "肌荒れ", "肌あれ"]


def 止まる(文: str) -> None:
    print(f"::error::{文}")
    sys.exit(1)


def 見せる(文: str) -> None:
    print(f"::warning::{文}")


# ------------------------------------------------------------------
# どの日を埋めるか
# ------------------------------------------------------------------
def 埋める日() -> datetime:
    指定 = os.environ.get("TARGET_DATE", "").strip()
    if 指定:
        return datetime.strptime(指定, "%Y-%m-%d").replace(tzinfo=JST)
    いま = datetime.now(JST)
    # 7時より前なら今日、それ以降なら明日（次に来る 07:00 の日）
    日 = いま if いま.hour < 7 else いま + timedelta(days=1)
    return 日.replace(hour=0, minute=0, second=0, microsecond=0)


def 枠のid(日: datetime, hhmm: str) -> str:
    return f"p-beauty-{日:%m%d}-{hhmm[:2]}"


# ------------------------------------------------------------------
# queue（読む → 変える → 書く を必ず別の文に分ける。2026-09-25 の事故の再発防止）
# ------------------------------------------------------------------
def queue_を読む() -> list[str]:
    return QUEUE_PATH.read_text(encoding="utf-8").splitlines(keepends=True)


def 入っているid(lines: list[str]) -> set[str]:
    出 = set()
    for l in lines:
        s = l.strip()
        if s and not s.startswith("#"):
            try:
                出.add(json.loads(s).get("id"))
            except json.JSONDecodeError:
                pass
    return 出


def queue_に足す(新しい行: list[dict]) -> None:
    lines = queue_を読む()
    前 = len(lines)
    足す = [json.dumps(x, ensure_ascii=False) + "\n" for x in 新しい行]
    if lines and not lines[-1].endswith("\n"):
        lines[-1] = lines[-1] + "\n"
    全部 = lines + 足す
    QUEUE_PATH.write_text("".join(全部), encoding="utf-8")
    後 = len(queue_を読む())
    if 後 != 前 + len(足す):
        止まる(f"queue の行数が合いません（{前} → {後}、足したのは {len(足す)}）。書き込みを疑ってください")
    print(f"queue: {前}行 → {後}行")


# ------------------------------------------------------------------
# 候補を選ぶ
# ------------------------------------------------------------------
def 取ってくる(url: str, 上限: int = 400_000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; yu-beauty/1.0)"})
    with urllib.request.urlopen(req, timeout=40) as res:
        生 = res.read(上限)
        文字 = res.headers.get_content_charset()
    for enc in [文字, "utf-8", "euc-jp", "shift_jis", "cp932"]:
        if not enc:
            continue
        try:
            return 生.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return 生.decode("utf-8", errors="replace")


def 候補を読む() -> list[dict]:
    try:
        text = 取ってくる(候補のURL + f"?t={int(datetime.now().timestamp())}")
    except Exception as e:  # noqa: BLE001
        止まる(f"美容の候補を読めませんでした（{e}）")
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def ログを読む() -> list[dict]:
    if not ログの置き場.exists():
        return []
    return [json.loads(l) for l in ログの置き場.read_text(encoding="utf-8").splitlines() if l.strip()]


def 自動で選ぶ(候補: list[dict], ログ: list[dict], 日: datetime) -> tuple[dict, str]:
    最近 = {
        x.get("itemCode") for x in ログ
        if x.get("埋めた日") and (日 - datetime.strptime(x["埋めた日"], "%Y-%m-%d").replace(tzinfo=JST)).days < 同じ商品を空ける日数
    }
    残り = []
    for c in 候補:
        名 = c.get("名", "")
        if (c.get("価格") or 0) > 自動の上限価格:
            continue
        if any(w in 名 for w in 自動で避ける語):
            continue
        if c.get("itemCode") in 最近:
            continue
        残り.append(c)
    if not 残り:
        止まる("自動で選べる候補がありません（価格・脱毛器・直近14日の重複で全部外れました）")
    # 薬用（医薬部外品）を先に。書ける幅が広い。あとはリサーチ担当の並び（点の順）
    残り.sort(key=lambda c: (not c.get("薬用"), c.get("番号", 99)))
    選 = 残り[0]
    理由 = (f"自動（代表の返信なし・期限1:00）。{自動の上限価格:,}円以下・脱毛器を除く・直近{同じ商品を空ける日数}日に使っていない"
          f"候補のうち{'薬用で' if 選.get('薬用') else ''}いちばん上の番号{選.get('番号')}")
    return 選, 理由


def リンクを確かめる(link: str) -> str:
    link = link.strip()
    if re.fullmatch(r"https://a\.r10\.to/[A-Za-z0-9]{5,8}", link):
        return link
    if link.startswith("https://hb.afl.rakuten.co.jp/"):
        return link
    止まる(f"リンクの形が違います: {link[:60]}")
    return ""


def 素の商品ページ(c: dict) -> str:
    u = c.get("商品ページ", "")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
    return (q.get("pc") or [u])[0]


# ------------------------------------------------------------------
# Claude
# ------------------------------------------------------------------
def 聞く(api_key: str, model: str, prompt: str, max_tokens: int = 8000) -> str:
    body = json.dumps({"model": model, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(API, data=body, method="POST")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=240) as res:
            data = json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        止まる(f"Anthropic API エラー ({e.code}): {e.read().decode(errors='replace')[:400]}")
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def 読みながら聞く(api_key: str, model: str, prompt: str, max_tokens: int = 8000) -> str:
    """Anthropic の web_fetch を使って、Claude 自身にページを開かせる。

    GitHub の実行環境から楽天の商品ページを直接取ると、中身の無いページが返る
    （2026-09-26、区分も決め手も取れなかった）。Claude の web_fetch なら読める。
    web_fetch は途中で pause_turn を返すことがあるので、続きを頼んで回す。
    """
    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 6,
              "allowed_domains": ["item.rakuten.co.jp", "review.rakuten.co.jp"],
              "max_content_tokens": 40000}]
    data: dict = {}
    for 回 in range(5):
        body = json.dumps({"model": model, "max_tokens": max_tokens, "tools": tools,
                           "messages": messages}).encode()
        req = urllib.request.Request(API, data=body, method="POST")
        req.add_header("x-api-key", api_key)
        req.add_header("anthropic-version", "2023-06-01")
        req.add_header("content-type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=300) as res:
                data = json.loads(res.read().decode())
        except urllib.error.HTTPError as e:
            止まる(f"Anthropic API エラー ({e.code}): {e.read().decode(errors='replace')[:400]}")
        使った = sum(1 for b in data.get("content", []) if b.get("type") == "server_tool_use")
        print(f"web_fetch: stop_reason={data.get('stop_reason')} ／ 開いたページ {使った}（{回 + 1}回目）")
        if data.get("stop_reason") != "pause_turn":
            break
        messages.append({"role": "assistant", "content": data["content"]})
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def モデル(api_key: str) -> str:
    指定 = os.environ.get("ANTHROPIC_MODEL", "").strip()
    if 指定:
        return 指定
    req = urllib.request.Request("https://api.anthropic.com/v1/models?limit=100")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")
    with urllib.request.urlopen(req, timeout=60) as res:
        ids = [m["id"] for m in json.loads(res.read().decode()).get("data", [])]
    for kw in ("opus", "sonnet"):
        for i in ids:
            if kw in i:
                return i
    return ids[0]


def JSONを取る(text: str):
    m = re.search(r"```json\s*(.*?)```", text, re.S)
    素 = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(素)


def 事実を確かめる(api_key, model, c) -> dict:
    ページ = 素の商品ページ(c)
    prompt = f"""楽天の商品を調べます。web_fetch でページを開き、**書いてあることだけ**を抜き出してください。
推測・補足・一般論は一切入れないでください。書いていないものは null にしてください。

1. 商品ページを開く: {ページ}
2. 商品ページの中にある「レビュー」へのリンク（review.rakuten.co.jp/item/1/…）を開く。
   並びが選べるなら「参考になった順」。★5と★1・★2を探して読む（2〜3ページまで）

# 商品名（楽天）
{c.get('名')}

# 返す形（JSONだけ。前置き不要）
```json
{{
  "短い商品名": "ブランド名＋商品の種類（例：レステモ 薬用美白ゲルクリーム）",
  "ブランド": "ブランド名だけ（例：レステモ）",
  "区分": "医薬部外品 / 化粧品 / 美容機器（美顔器・ドライヤー・脱毛器など） / 不明 のどれか",
  "有効成分": ["医薬部外品のときだけ"],
  "承認された効能": ["医薬部外品のときだけ。ページの文言をそのまま。言い換えない"],
  "容量": "例：500g",
  "使い方": "ページの文言をそのまま短く",
  "役割": ["オールインワンなら何役か。ページにあるものだけ"],
  "主な成分": ["配合目的がページに書いてあれば『成分名（目的）』の形で"],
  "仕様": ["美容機器のとき：温度・モード・重さ・充電など、ページにある仕様"],
  "詰め替え": "あり / なし / 不明",
  "レビュー件数": 数字か null,
  "レビュー平均": 数字か null,
  "星5の決め手": ["★5レビューに書いてある『買った決め手』。1件1行・本文にあることだけ・最大7件"],
  "星1の理由": ["★1・★2に書いてある『買わない理由』。見つからなければ空"],
  "使ってはいけない声": ["レビューにあるが、効能を言いすぎていて投稿に使えないもの（シミが薄くなった等）"],
  "読めたページ": ["実際に開けたURL"]
}}
```"""
    return JSONを取る(読みながら聞く(api_key, model, prompt))


def 投稿を書かせる(api_key, model, 事実, 前回の失敗=None) -> list[dict]:
    医薬 = 事実.get("区分") == "医薬部外品"
    prompt = f"""あなたは運営事業部の「切り口担当」と「投稿ライター」です。
下の商品について、**5人ぶんの違う悩み**に割り、Threads の投稿を5本書いてください。

# 確かめた事実（ここに無いことは書かない）
```json
{json.dumps(事実, ensure_ascii=False, indent=1)}
```

# 投稿の形（成分表型）
- 【本文】（1投稿目）：その人の悩みから始める。役に立つ短い表や手順を置いてもよい。
  最後は必ず「それは、「」で切る（次の投稿で商品名を言う）
  **本文に商品名・ブランド名・URL・PR・【PR】を書かない**
- 【返信】（2投稿目）：「{事実.get('短い商品名')}」から始める。事実を短く並べる。
  リンクを置く場所に **LINK** とだけ書く（URLは書かない）。**最後の行は小文字で pr**

# 切り口の決まり
- 材料は「星5の決め手」と「星1の理由」だけ。そこに無い悩みは作らない
- 5本は「誰」がちがうこと。年齢・性別で割らない。効能で割らない。場面と手間で割る

# 絶対に守ること（薬機法）
- この商品は **{事実.get('区分')}**
{"- 効能を書くときは「承認された効能」の文言を**そのまま**使う。言い換えない。「防ぐ」までしか言えない" if 医薬 else ("- **美容機器なので、肌や体への効果は一切書かない。** 書けるのは使う場面・手間・ページにある仕様（温度・モード・重さ・充電など）だけ" if "機器" in str(事実.get("区分")) else "- **効能は書かない**（化粧品）。防ぐ・美白・シミ・ニキビ・肌荒れ は書けない。成分は『成分名（配合目的）』の形でだけ書く")}
- 書いてはいけない：消える・薄くなる・治る・改善・効く・万能・最強・No.1・一番・絶対・必ず・誰でも・毛穴・くすみ・たるみ・エイジング・敏感肌でも・永久・若返る・痩せる
- 「使ってはいけない声」は使わない
- **「使ってみた」「使ったら」と書かない**（代表はこの商品を使っていない）。レビューの声として書く
- **価格を書かない**（セールで変わる）。「◯円」は一切書かない
- 1本500字まで

{"# 前回はねられた理由（直してください）" + chr(10) + 前回の失敗 if 前回の失敗 else ""}

# 返す形（JSONだけ）
```json
[{{"誰": "…", "悩み": "…", "効くところ": "…", "本文": "…", "返信": "…"}}, …5本]
```"""
    return JSONを取る(聞く(api_key, model, prompt, 10000))


def 見張る(p: dict, 事実: dict) -> list[str]:
    ng = []
    本文, 返信 = p.get("本文", ""), p.get("返信", "")
    医薬 = 事実.get("区分") == "医薬部外品"
    ブランド = (事実.get("ブランド") or "").strip()
    if ブランド and ブランド in 本文:
        ng.append(f"本文にブランド名「{ブランド}」")
    if re.search(r"https?://|【PR】|\bPR\b|#PR", 本文):
        ng.append("本文にリンクかPR")
    if not 本文.rstrip().endswith("「"):
        ng.append("本文が「それは、「」で終わっていない")
    if 返信.count("LINK") != 1:
        ng.append("返信の LINK が1つではない")
    if not 返信.rstrip().endswith("pr"):
        ng.append("返信の末尾が pr でない")
    if re.search(r"https?://", 返信):
        ng.append("返信にURLを書いている")
    for 語 in いつでも駄目:
        if 語 in 本文 or 語 in 返信:
            ng.append(f"禁止語「{語}」")
    if not 医薬:
        for 語 in 化粧品なら駄目:
            if 語 in 本文 or 語 in 返信:
                ng.append(f"化粧品で書けない語「{語}」")
    if re.search(r"\d[\d,]*\s*円", 本文 + 返信):
        ng.append("価格を書いている")
    if re.search(r"使ってみ|使ったら|使ってる|愛用", 本文 + 返信):
        ng.append("使ったと書いている")
    if len(本文) > 500 or len(返信.replace("LINK", "x" * 30)) > 500:
        ng.append("500字超え")
    return ng


# ------------------------------------------------------------------
def 予備で埋める() -> None:
    """本番が失敗したときの最後の手。予備の投稿を古い順に空き枠へ入れる。

    予備は前の商品の切り口の残り（リンク差し込み済み・見張り済み）。
    これが無ければ枠は空のまま。空で出すほうが、見張っていない投稿を出すよりまし。
    """
    日 = 埋める日()
    lines = queue_を読む()
    すでに = 入っているid(lines)
    空き = [(h, 枠のid(日, h)) for h in 枠 if 枠のid(日, h) not in すでに]
    if not 空き:
        print("美容の枠は全部埋まっています。予備は使いません。")
        return
    if not 予備の置き場.exists():
        見せる(f"予備がありません。{日:%m/%d} の美容 {len(空き)}枠は空のままです")
        return
    予備 = [json.loads(l) for l in 予備の置き場.read_text(encoding="utf-8").splitlines() if l.strip()]
    使う, 残す = 予備[:len(空き)], 予備[len(空き):]
    if not 使う:
        見せる(f"予備が0件です。{日:%m/%d} の美容 {len(空き)}枠は空のままです")
        return
    新 = [{
        "id": i, "text": p["本文"], "scheduled_at": f"{日:%Y-%m-%d}T{h}:00+09:00",
        "thread": [p["返信"]], "note": f"運営事業部・美容／{p.get('商品')}／切り口：{p.get('切り口')}／予備から",
    } for (h, i), p in zip(空き, 使う)]
    if os.environ.get("DRY_RUN") == "1":
        for x in 新:
            見せる(f"（下見）予備で予約：{x['scheduled_at'][11:16]} … {x['note']}")
        return
    queue_に足す(新)
    予備の置き場.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in 残す), encoding="utf-8")
    for x in 新:
        見せる(f"予備で予約：{x['scheduled_at'][11:16]} … {x['note']}")
    if len(新) < len(空き):
        見せる(f"※ 予備が足りず、{len(空き) - len(新)}枠は空のままです")


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        止まる("ANTHROPIC_API_KEY がありません")
    日 = 埋める日()
    ids = [枠のid(日, h) for h in 枠]
    lines = queue_を読む()
    すでに = 入っているid(lines)
    空き = [(h, i) for h, i in zip(枠, ids) if i not in すでに]
    print(f"埋める日: {日:%Y-%m-%d} ／ 空いている枠: {[h for h, _ in 空き] or 'なし'}")
    if not 空き:
        print("美容の枠は全部埋まっています。何もしません。")
        return

    PICK = os.environ.get("PICK", "").strip()
    LINK = os.environ.get("LINK", "").strip()
    候補 = 候補を読む()
    ログ = ログを読む()
    if PICK:
        選 = next((c for c in 候補 if str(c.get("番号")) == PICK), None)
        if not 選:
            止まる(f"候補に番号 {PICK} がありません")
        理由, 決めた人 = "代表が選んだ", "代表"
    else:
        選, 理由 = 自動で選ぶ(候補, ログ, 日)
        決めた人 = "自動"
    link = リンクを確かめる(LINK or 選.get("商品ページ", ""))

    # 台帳の照合：同じリンクが別の商品に付いていないか
    for x in ログ:
        if x.get("リンク") == link and x.get("itemCode") != 選.get("itemCode"):
            止まる(f"このリンクは別の商品（{x.get('商品')}）に使われています。使いません")

    見せる(f"【{日:%m/%d} の美容】{決めた人}：番号{選.get('番号')} {選.get('名','')[:40]}")
    見せる(f"理由：{理由}")

    model = モデル(api_key)
    事実 = 事実を確かめる(api_key, model, 選)
    見せる(f"区分：{事実.get('区分')} ／ 決め手 {len(事実.get('星5の決め手') or [])}件 ／ 星1 {len(事実.get('星1の理由') or [])}件")
    見せる(f"読めたページ：{' ／ '.join(事実.get('読めたページ') or []) or 'なし'}")
    if not (事実.get("星5の決め手")):
        止まる("レビューから決め手が1つも取れませんでした。材料が無いまま書かせない")

    通った: list[dict] = []
    失敗 = None
    for 回 in (1, 2):
        for p in 投稿を書かせる(api_key, model, 事実, 失敗):
            ng = 見張る(p, 事実)
            if ng:
                見せる(f"はねた：{p.get('誰','?')} … {' ／ '.join(ng)}")
                失敗 = (失敗 or "") + f"\n- {p.get('誰','?')}: {' ／ '.join(ng)}"
            elif all(p.get("誰") != q.get("誰") for q in 通った):
                通った.append(p)
        if len(通った) >= len(空き) + 1 or (回 == 2):
            break
    if not 通った:
        止まる("見張りを通った投稿が1本もありません")

    見せる(f"見張り：通った {len(通った)}本")
    if os.environ.get("DRY_RUN") == "1":
        # 注記は1ステップ10件までしか残らないので、全文はファイルに書く（ワークフローがこれだけコミットする）
        書 = [f"# 美容の下見 {日:%Y-%m-%d}（{決めた人}：番号{選.get('番号')}）", "",
             f"- 商品：{事実.get('短い商品名')}（{事実.get('区分')}）", f"- 理由：{理由}", ""]
        for n, p in enumerate(通った, 1):
            書 += [f"## {n}. {p.get('誰')}", f"悩み：{p.get('悩み')}", "", "【本文】", "```", p["本文"].strip(), "```",
                  "【返信】", "```", p["返信"].replace("LINK", link).strip(), "```", ""]
        Path("neta/美容_下見.md").write_text("\n".join(書), encoding="utf-8")
        print("DRY_RUN なので queue には入れません。neta/美容_下見.md に書きました。")
        return

    新 = []
    for (h, i), p in zip(空き, 通った):
        新.append({
            "id": i,
            "text": p["本文"].strip(),
            "scheduled_at": f"{日:%Y-%m-%d}T{h}:00+09:00",
            "thread": [p["返信"].replace("LINK", link).strip()],
            "note": f"運営事業部・美容／{事実.get('短い商品名')}／切り口：{p.get('誰')}／{決めた人}が決定",
        })
    queue_に足す(新)
    for x in 新:
        見せる(f"予約：{x['scheduled_at'][11:16]} … {x['note'].split('／')[2]}")

    予備 = 通った[len(新):]
    if 予備:
        with 予備の置き場.open("a", encoding="utf-8") as f:
            for p in 予備:
                f.write(json.dumps({
                    "作った日": datetime.now(JST).strftime("%Y-%m-%d"), "商品": 事実.get("短い商品名"),
                    "本文": p["本文"].strip(), "返信": p["返信"].replace("LINK", link).strip(),
                    "切り口": p.get("誰"),
                }, ensure_ascii=False) + "\n")
    with ログの置き場.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "決めた日時": datetime.now(JST).isoformat(timespec="minutes"), "埋めた日": f"{日:%Y-%m-%d}",
            "決めた人": 決めた人, "番号": 選.get("番号"), "itemCode": 選.get("itemCode"),
            "商品": 事実.get("短い商品名"), "区分": 事実.get("区分"), "理由": 理由, "リンク": link,
            "予約": [x["scheduled_at"][11:16] for x in 新], "予備": len(予備),
        }, ensure_ascii=False) + "\n")
    if len(新) < len(空き):
        見せる(f"※ {len(空き)}枠のうち {len(新)}枠しか埋まりませんでした")


if __name__ == "__main__":
    if os.environ.get("USE_SPARE") == "1":
        予備で埋める()
    else:
        main()
