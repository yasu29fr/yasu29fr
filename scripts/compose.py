"""翌日ぶんの Threads 投稿 3 本を作成し、投稿キューに追加する。

発信の中心は Instagram の運用ノウハウと、動画編集・リール制作。

外部 cron から毎日 20:00 JST に起動される想定。

材料:
  - 運用ボード（Google ドキュメント / リンクを知っている全員が閲覧可）
  - ネタ帳（同上）
  - posts/queue.jsonl の直近の投稿（重複回避のため）

必要な環境変数:
  ANTHROPIC_API_KEY  必須。Anthropic の API キー
  BOARD_DOC_ID       任意。運用ボードの Google ドキュメント ID
  NETA_DOC_ID        任意。ネタ帳の Google ドキュメント ID
                     （neta/ネタ帳.md があるときは、そちらが優先される）
  ANTHROPIC_MODEL    任意。使うモデル。未指定なら利用可能なものから自動で選ぶ
  DRY_RUN            任意。"true" なら生成結果を表示するだけでファイルを書き換えない
"""

from __future__ import annotations

import json
import os
import re
import random
import string
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import お得日
import 商品
import 宿

JST = ZoneInfo("Asia/Tokyo")
QUEUE_PATH = Path("posts/queue.jsonl")
API_BASE = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"

# 予約する時刻と、その枠の役割
#
# 発信の中心は Instagram の運用ノウハウと、動画編集・リール制作。
# 朝と昼はこの 2 領域に固定し、夜だけ幅を持たせる。毎日同じ話題が並ぶと
# 読み飽きるので、逃げ場を 1 枠だけ用意してある。
POLICY_CORE = """## 発信方針（2026-09-13 確定。ここが最優先の考え方）

読まれるかどうかは、書き出しが「外の話」か「自分たちの話」かで決まる。
同じアカウント・同じ書き手で、外の出来事から入った投稿は表示 2,820、
自社の作業手順から入った投稿は表示 6 だった。470 倍の差がある。

だから、投稿は次の順で組み立てる。

① 世の中・身近な出来事        ← 1行目。ここで読まれるかが決まる
② それによって起こる変化
③ 読者に発生する悩み・欲求     ← ここを飛ばすと「なんで？」になる
④ 必要になる行動
⑤ 商品・サービスにつながる解決策

**どこで止めるかは枠ごとに指定する（深さ A〜C）。指定より深く着地しないこと。**
- A: ①だけ。出来事の共有で終える
- B: ③まで。問題提起で止める（主力）
- C: ⑤まで。ただし商品名・サービス名・URLは書かない

すべての投稿を ⑤ まで着地させてはいけない。毎回着地させると ① が
売り込みの前振りに見え、① ごと読まれなくなる。

### 1行目の決まり
- 自分・自社・自社の商品の話で始めない
- 「〜しています」で始めない。断言か数字で始める
- 主語を「わたし」「うち」「当社」にしない
- 「作りました」「できました」で始めない（実測で平均の3分の1しか読まれない）

### つなげない話題
災害、事件、病気など、人の被害が絡む出来事は、商品にも自分たちのテーマにも
つなげない。論理が通っても感情が通らない。
"""

POLICY_ACCOUNT = """### この出来事を見るときに通す質問

**「この出来事は、動画編集や SNS 発信をしている人に何が使える？」**（2026-09-18 変更）

読者は「一人で回している人」に限りません。**動画編集や SNS 発信をしている人全般**です。
会社で担当している人、チームでやっている人も含みます。

ニュースや出来事の解説は書かない。書くのは「で、この読者に何が使えるか」だけ。

### 扱う範囲（2026-09-18 拡張）

- **ツールの新機能・値下げ・提供開始**（Instagram / Threads / TikTok / YouTube /
  Adobe / Canva / CapCut / 生成AI など）
- **各SNSの仕様変更**
- **人が紹介していて良さそうなツール。** 自分で使っていなくてよい
- **いま話題になっているもの**（トレンド）
- **福井のおでかけ情報**（17:00 の枠）
- 自分が作った「ミテカラ」の紹介（これは 12:30 の専用枠で出すので、通常枠では扱わない）
- 道具の紹介（アフィリエイト）は、毎日 6:00 の枠だけ。【PR】表記を付ける。
  他の枠では商品名を出した紹介をしない

**使っていないものを「使った」と書かないこと。** ここがいちばん危ないところです。
人の紹介で知ったツールは「気になっています」「まだ試していません」と書く。
自分で確かめた話と、人から聞いた話を混ぜない。

### 読者に起きている「瞬間」（③④の材料。ここから1つ選ぶ）

- 投稿しようと思ったまま、3日経っている
- 繁忙期に入って、まず発信が止まった
- 下書きが溜まっているのに、投稿できない
- ネタはあるのに、文章にする20分が取れない
- 予約投稿ツールを契約したが、そこに入力する時間がない
- 複数アカウントを持っていて、全部は回らない
- 毎日「今日は何を書こう」から始めている
- 他人の投稿を見るほど、何を書けばいいか分からなくなる
- ネタを増やせば楽になると思っている（が、楽にならない）
- 業者に頼むと月数万円。それを払うほどではない
- 客には「毎日投稿を」と言っているのに、自分が止まっている
- 独立したばかりで、まず知ってもらう必要がある
- AIに書かせてみたが、自分の言葉にならなかった
- AIに書かせたら、やっていないことを書かれた
- 生成AIを仕事に使いたいが、何から手を付けるか決まらない
- 仕組みを作りたいが、プログラミングができない
- 一度作った仕組みが壊れて、直せなかった
- 無料ツールを使っていたが、仕様変更で止まった
- 新しい機能が出たのは知っているが、自分の作業のどこで使えるか分からない
- 話題のツールを試す時間が取れず、判断だけ先送りになっている
- 編集の手順が人によってばらばらで、引き継げない
- 使っているツールが値上げ・仕様変更して、乗り換えるか迷っている
"""

DEPTH = {6: "B", 12: "B", 17: "A", 20: "C"}

SLOTS = [
    (
        6,
        "Instagram の運用ノウハウ",
        "B（ノウハウ型）またはA（気づき型）",
        "起き抜けに読んで、その日の投稿づくりにすぐ使える",
    ),
    (
        12,
        "動画編集・リール制作の中身",
        "C（裏側型）またはB（ノウハウ型）",
        "手を動かしている人だと伝わる。作業の具体が見える",
    ),
    (
        17,
        "福井のおでかけ情報",
        "F（紹介型）",
        "仕事終わりに読まれる。福井で今なにが起きているかを知れる",
    ),
    (
        20,
        "発信の自動化・仕組み化（note 記事につながる話題）",
        "E（問いかけ型）またはA（気づき型）",
        "note 記事に関心を持ってもらう。ただし記事の宣伝はしない",
    ),
    (
        21,
        "楽天のお得日のお知らせ",
        "F（紹介型）",
        "お得日（1日・5と0のつく日・18日）だけ出る枠。該当しない日はこの枠を作らない",
    ),
]

# 未指定のときに上から順に探すモデル
MODEL_PREFERENCE = ("opus", "sonnet", "haiku")


# 紹介（アフィリエイト）を入れてよい枠。毎日 1 本。
#
# 12:00 を使っていないのは、12:30 にミテカラ LP の枠が毎日入っているため。
# 30 分ちがいで宣伝が 2 本並ぶのを避けて、朝いちばんに置いている。
PR_HOUR = 6


# 紹介する商品は scripts/商品.py が選ぶ。リストは X のリポジトリの
# neta/商品.jsonl ただ 1 つで、X も yu も同じものを読む。
# 選び方は日付から計算するので、同じ日なら両方のアカウントで同じ商品になる。
# URL は AI に渡さず、リストにある文字列をそのまま投稿に入れる。
# AI に URL を書かせると、1 文字変わっただけで別の場所へ飛ぶため。

PR_MARKERS = ("【PR】", "#PR", "＃PR", "[PR]")

URL_IN_TEXT = re.compile(r"https?://\S+")

# 楽天の検索で入れた商品には、メモの先頭に「[未使用]」が付く
# （scripts/商品を取る.mjs）。本人が使ったことのある商品と書き分けるための印。
UNUSED_MARK = 商品.未使用の印

# 未使用の商品でこれが出たら止める。検索で見つけただけの道具に
# 「使っている」と書かせると、それはただの嘘になる。
# このアカウントの方針「使っていないものを『使った』と書かない」を機械で守る。
USED_VOICE = re.compile(
    r"使って(み|い)|使った|使ってる|愛用|買ってよかった|買って良かった|"
    r"届いた|試した|試してみ|導入して|乗り換え(た|て)|手放せ|使い始め"
)


def is_unused(product: dict | None) -> bool:
    """本人がまだ使っていない商品か。"""
    return bool(product) and UNUSED_MARK in (product.get("memo") or "")


def product_rules(product: dict) -> list[str]:
    """商品の出どころで 4 番目の決まりを差し替える。"""
    if is_unused(product):
        return [
            "4. **この商品を、本人はまだ使っていません。**",
            "   「使っている」「使ってみた」「買ってよかった」「愛用」は書かないこと。",
            "   書けるのは、何をする道具か・どんな場面で要るか・どんな人に向くか、",
            "   そして **自分はまだ試していない** ということだけです。",
            "   「気になっています」「まだ試していません」のように、"
            "未使用だと分かる形で書いてください",
        ]
    return ["4. スペックの列挙にしない。実際に使ってどうだったかを書く"]


LEARNINGS_PATH = Path("insights/learnings.md")


def learning_section() -> list[str]:
    """検証チーム（scripts/review.py）が毎日更新する指示を読む。無ければ何も足さない。"""
    if not LEARNINGS_PATH.exists():
        return []
    text = LEARNINGS_PATH.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [
        "## 検証チームからの指示（直近 7 日の数字に基づく）",
        "以下は実際の閲覧・反応の数字から決めた指示です。切り口・長さ・連投・話題の比重はこれに従ってください。",
        "ただし、運用ボードの文体・禁止事項・事実の扱いを超えることはできません。食い違えば運用ボードを優先します。",
        text,
        "",
    ]


def fail(message: str) -> None:
    print(f"::error::{message}")
    sys.exit(1)


def fetch_doc(doc_id: str, label: str) -> str:
    """Google ドキュメントをプレーンテキストで取得する。

    「リンクを知っている全員が閲覧可」になっていれば認証なしで読める。
    読めなくても処理は止めず、その材料なしで続ける。
    """
    if not doc_id:
        print(f"{label}: ID が未設定のため読み込みません。")
        return ""
    url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                print(f"::warning::{label}: 取得できませんでした (HTTP {response.status})")
                return ""
            text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - 材料が欠けても続行する
        print(f"::warning::{label}: 取得に失敗しました ({exc})")
        return ""
    print(f"{label}: {len(text)} 文字を読み込みました。")
    return text


NETA_PATH = Path("neta/ネタ帳.md")


def read_neta() -> str:
    """ネタ帳を読む。リポジトリの中にあれば、それを使う。

    2026-09-14 に置き場所を Google ドキュメントからこのリポジトリへ移した。
    毎朝の自動収集（.github/workflows/neta-collect.yml）がここに追記する。
    ファイルが無いときだけ、従来どおり NETA_DOC_ID のドキュメントを読む。
    移行の途中でも、どちらか読めたほうで動く。
    """
    if NETA_PATH.exists():
        text = NETA_PATH.read_text(encoding="utf-8")
        print(f"ネタ帳: {NETA_PATH} から {len(text)} 文字を読み込みました。")
        return text
    return fetch_doc(os.environ.get("NETA_DOC_ID", "").strip(), "ネタ帳")


def api_request(method: str, path: str, api_key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(API_BASE + path, data=data, method=method)
    request.add_header("x-api-key", api_key)
    request.add_header("anthropic-version", API_VERSION)
    request.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        fail(f"Anthropic API エラー ({exc.code}): {detail}")
    except Exception as exc:  # noqa: BLE001
        fail(f"Anthropic API に接続できませんでした: {exc}")
    return {}


def pick_model(api_key: str) -> str:
    """使うモデルを決める。指定がなければ利用可能なものから選ぶ。"""
    explicit = os.environ.get("ANTHROPIC_MODEL", "").strip()
    if explicit:
        return explicit
    payload = api_request("GET", "/models?limit=100", api_key)
    ids = [m["id"] for m in payload.get("data", [])]
    if not ids:
        fail("利用できるモデルが見つかりませんでした。ANTHROPIC_MODEL を指定してください。")
    for keyword in MODEL_PREFERENCE:
        for model_id in ids:
            if keyword in model_id:
                print(f"モデル: {model_id}")
                return model_id
    print(f"モデル: {ids[0]}")
    return ids[0]


def read_queue_lines() -> list[str]:
    if not QUEUE_PATH.exists():
        fail(f"キューが見つかりません: {QUEUE_PATH}")
    return QUEUE_PATH.read_text(encoding="utf-8").splitlines()


def parse_entries(lines: list[str]) -> list[dict]:
    entries = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            entries.append(json.loads(stripped))
        except json.JSONDecodeError:
            continue
    return entries


def recent_texts(entries: list[dict], count: int | None = None) -> str:
    """直近の投稿を「日時・1 行目・使ったネタ」の形で返す。

    重複を避けるのが目的なので、本文全部ではなく 1 行目と note だけを渡す。
    件数は 1 日の枠数 × 7 日（2026-09-18 変更。固定件数だと本数の多い
    アカウントで 2 日ぶんしか見えず、同じネタが何度も出ていた）。
    """
    if count is None:
        count = max(len(SLOTS) * 7, 20)
    # キューはファイル順が時系列とは限らない（あとから別の枠を足すことがある）。
    # 予約時刻で並べ直し、まだ出ていないものは除いてから直近を取る。
    now = datetime.now(JST).isoformat()
    dated = [e for e in entries if isinstance(e.get("scheduled_at"), str)]
    past = sorted((e for e in dated if e["scheduled_at"] <= now), key=lambda e: e["scheduled_at"])
    parts = []
    for entry in past[-count:]:
        first = (entry.get("text", "") or "").split("\n")[0].strip()
        when = (entry.get("scheduled_at") or "")[5:16].replace("T", " ")
        note = (entry.get("note") or "").strip()
        line = f"- {when} ｜ {first}"
        if note:
            line += f"  〔{note}〕"
        parts.append(line)
    return "\n".join(parts)


def find_filled(entries: list[dict], target_date) -> dict[int, dict]:
    """対象日にすでに予約が入っている枠を、時 -> 投稿 の形で返す。"""
    prefix = target_date.isoformat()
    filled: dict[int, dict] = {}
    for entry in entries:
        scheduled = entry.get("scheduled_at")
        if not isinstance(scheduled, str) or not scheduled.startswith(prefix):
            continue
        # 12:30 のような枠外の予約が 12:00 の枠を埋めたことにならないよう、
        # 分が 00 のものだけを「枠が埋まっている」とみなす
        if scheduled[14:16] != "00":
            continue
        try:
            hour = int(scheduled[11:13])
        except (ValueError, IndexError):
            continue
        filled[hour] = entry
    return filled


def describe_filled(filled: dict[int, dict]) -> str:
    if not filled:
        return ""
    parts = []
    for hour in sorted(filled):
        entry = filled[hour]
        thread = " ".join(entry.get("thread") or [])
        parts.append(f"- {hour}:00 ｜ {entry.get('text','')} {thread}".strip())
    return "\n".join(parts)


def build_prompt(
    board: str,
    neta: str,
    recent: str,
    target_date,
    needed,
    filled,
    product: dict | None = None,
    pr_hour: int | None = None,
    hotel: dict | None = None,
    hotel_hour: int | None = None,
    deal: dict | None = None,
    deal_hour: int | None = None,
) -> str:
    slot_lines = "\n".join(
        f"- {hour}:00 ｜ 深さ: {DEPTH.get(hour, 'B')} ｜ 柱: {pillar} ｜ 型: {form} ｜ ねらい: {aim}"
        for hour, pillar, form, aim in needed
    )
    weekday = "月火水木金土日"[target_date.weekday()]
    hours = "、".join(f"{hour}:00" for hour, *_ in needed)
    already = describe_filled(filled)
    sections = [
        "あなたは YU さん（福井市のフリーランス Web クリエイター／SNS コンテンツ制作者）の",
        "Threads 発信チームの編集担当です。",
        f"{target_date.isoformat()}（{weekday}）の {hours} に投稿する {len(needed)} 本を書いてください。",
        "",
        "## 枠と役割",
        slot_lines,
        "",
        "## 話題の方針（運用ボードの「コンテンツの柱」「時間帯ごとの担当」より優先）",
        "この発信は Instagram の運用ノウハウと、動画編集・リール制作の話を中心にします。",
        "6:00 と 12:00 は、必ずこの 2 領域のどちらかにしてください。",
        "Web サイト制作や印刷デザインの話は、Instagram・動画の話につながるときだけ触れてください。",
        "",
        "## 20:00 の枠について（この枠だけ役割が違う）",
        "20:00 は「発信の自動化・仕組み化」を話題にします。note に書いた内容と地続きの枠です。",
        "扱うのは、たとえば次のようなことです。",
        "- 投稿が続かなかった頃のこと。何に詰まっていたか",
        "- 毎日ゼロから決め直すことの負荷。判断の回数を減らすという考え方",
        "- 予約投稿や自動化を実際に使ってみて分かったこと、うまくいかなかったこと",
        "- AI に書かせることの限界。材料がないと薄くなること",
        "- 仕組みに任せた結果、自分の時間の使い方がどう変わったか",
        "",
        "**厳守すること**",
        "- **URL を書かない。** note・記事・リンクという語も本文に出さない",
        "- 「詳しくはこちら」「記事に書きました」のような誘導を書かない",
        "- 宣伝の語調にしない。**あくまで自分の体験として語る**",
        "- 売り込みに読めたら失敗。読んだ人が「同じことで困っている」と感じる形にする",
        "- 他の枠と同じ文体・長さを守る",
        "",
    ]
    if already:
        sections += [
            "## 同じ日にすでに入っている投稿（YU さん本人が用意したもの）",
            "これらとネタ・切り口・書き出しが重ならないようにしてください。",
            "文体もこれらに寄せてください。",
            already,
            "",
        ]
    if product and pr_hour is not None:
        sections += [
            f"## {pr_hour}:00 の枠だけ、商品の紹介です",
            "",
            f"紹介する商品: {product['name']}",
            f"本人のメモ: {product['memo'] or '（なし）'}",
            "",
            "この枠の書き方には、守っていただく決まりがあります。",
            "",
            "1. **本文の冒頭を必ず「【PR】」で始める。** 末尾ではなく先頭です（ステマ規制）",
            "2. **URL は絶対に書かない。** リンクはこちらで別に付けます。",
            "   「詳細はこちら」のような誘導文も本文に入れないこと",
            "3. 本人のメモに書かれている範囲のことだけを書く。",
            "   確かめていない良さを足さないこと",
            *product_rules(product),
            "5. 「買うべき」「おすすめです」と言い切らない。判断は読む人に任せる",
            "6. 合わない人・向かない場面にも一言触れる。良いことだけ並べない",
            "",
            "本文は【PR】を含めて日本語 60〜120 字。**THREAD は書かないでください。**",
            "（リンクだけの連投をこちらで 1 件付けます）",
            "",
        ]
    if not product:
        sections += [
            "## 今日は商品の紹介をしません",
            "",
            "紹介できる商品が用意されていません。**どの枠でも商品紹介を書かないでください。**",
            "",
            "- 本文を「【PR】」「#PR」「[PR]」で始めない",
            "- 特定の商品名を出して、良さを伝える書き方をしない",
            "- 購入をすすめる書き方をしない",
            "",
            "材料に商品の情報があっても、今日は使いません。",
            "道具の話をする場合は、**商品名を出さずに**、やり方や気づきとして書いてください。",
            "",
        ]
    sections += [
        *learning_section(),
        "## 運用ボード（文体・書かないこと・品質基準の最優先ルール）",
        "上の「話題の方針」と食い違うときだけ、話題の方針を優先してください。",
        "それ以外（文体・禁止事項・型・プロフィール）は、すべてボードに従います。",
        board or "（読み込めませんでした。以下の要点だけで書いてください）",
        "",
        "## ネタ帳（YU さん本人が書いた生の材料。最優先で使う）",
        neta or "（空です）",
        "",
        "## 同じネタ・同じ投稿の使い回し（2026-09-18 代表指示）",
        "",
        "同じネタを何度使ってもかまいません。**同じ日に重ねないことだけ守ってください。**",
        "",
        "- **同じ出来事（催し・店・記事）は、1 日に 1 本まで（2026-09-23 代表指示）。**",
        "  **同じかどうかは「出典元：」の URL で見ます。**",
        "  同じ URL を 1 日に 2 本以上使わないこと。時間を空ければよい、ではありません",
        "  （これまでの「1 日 2 本まで・4 時間以上あける」は廃止しました）",
        "- **2 日続けて同じ出来事を出さない。** 1 日あける",
        "  ただし **開催日まで 3 日以内の催しは、毎日 1 本まで出してよい**（直前の告知は効くため）",
        "- **同じ書き出し（1 行目）を同じ日に 2 回使わない。** 角度を変える",
        "- **本文をそのまま出し直すのは、前回から 7 日以上あいていれば可。**",
        "  伸びた投稿の再掲は歓迎します。ネタが薄い日は、新しく薄いものを作るより再掲のほうがよい",
        "",
        "## 直近 7 日の投稿（日時・1 行目・使ったネタ）",
        "",
        "**ここに出ている出来事・記事・切り口は、上のルールに照らして使えるかを必ず確認すること。**",
        recent or "（なし）",
        "",
        "## 冒頭 1 行（ここがいちばん効きます）",
        "",
        "**「〜しています」「〜するようにしています」で始めないこと。**",
        "自分の習慣の説明から入ると読まれません（測定値: 説明文の書き出し 17 本で平均閲覧 76.9、",
        "数字から入った 3 本は 169.7。会社アカウントでも短い断言が説明文の 2.7 倍）。",
        "",
        "次のどちらかで始めてください。",
        "",
        "1. **断言** — 言い切る。否定形の断言も強い",
        "   例:「専門用語を、全部やさしく言い換えるのが正解とは思っていません。」",
        "   例:「ホームページ制作で、いちばん時間をかけているのはデザインではありません。」",
        "2. **数字** — 具体的な数を先に置く",
        "   例:「提案書を 27 ページ書いて、全部捨てました。」",
        "",
        "**主語を「わたし」にしないこと。** 主語は、話題になっている物・事・読者にします。",
        "自分の体験は、断言したあとの根拠として 2 行目以降に置きます。",
        "",
        "冒頭 1 行には、検索で引っかかる具体的な語を 2 つ入れます",
        "（ツール名・機能名・作業名。「効率化」「工夫」「大切なこと」のような抽象語は数えません）。",
        "",
        POLICY_CORE,
        "",
        POLICY_ACCOUNT,
        "",
        "## 17:00「福井のおでかけ情報」の枠（2026-09-18 新設）",
        "",
        "福井県内の出来事・店・催し・展示を 1 件紹介する枠です。",
        "材料は下の「ネタ帳」から取ります。**出典が無い材料はこの枠で使わないこと。**",
        "",
        "- **本文に地名を必ず入れる。** 「福井」「鯖江」「越前」「小浜」「勝山」など県名か市町名",
        "- **イベント名・店名・施設名も、できるだけ本文に入れる**",
        "- 本文または thread の最後に **`出典元：URL`** を置く（URLは材料にあるものをそのまま使う。作らない）",
        "- この枠に限り、下の文体ルールの「リンクは貼らない」を適用しません",
        "",
        "### 会社アカウント（@fukui._.fukui）との書き分け",
        "",
        "**同じ催しを扱ってかまいません。ただし文章の感じを変えてください。**",
        "",
        "会社アカウントは福井のメディアとして「知らせる」立場で、",
        "「〜という記事が出ています」「〜だそうです」と書きます。",
        "",
        "こちらは **一人で仕事をしている個人**です。その出来事に自分がどう反応したか、",
        "自分の仕事とどうつながるかの距離感で書いてください。",
        "「行ってきました」「気になっています」「これは撮る側には効きそうです」のような書き方です。",
        "",
        "  会社: 鯖江でめがねフェス2026。今週末の2日間、めがねミュージアムと周辺会場で開かれるそうです。",
        "  こちら: 鯖江のめがねフェス、今年も今週末です。産地の工場が開く日なので、",
        "          撮らせてもらえる機会としても毎年気にしています。",
        "",
        "並べて読んでも重複に見えないようにします。**同じ文章にはしないこと。**",
        "",
        "材料が無い日は、無理に作らず柱を「Instagram の運用ノウハウ」に読み替えてください。",
        "",
        "## 連投の 1 本目（本文）について（2026-09-18 代表指示）",
        "",
        "**本文だけを読んで、何の話か分かるように書いてください。**",
        "thread を読まなくても「何について」「誰に関係するか」が伝わること。",
        "",
        "これまで「80 字に入りきらない分は thread に回す」と指示していたため、",
        "本文が言いかけで終わり、何の話か分からない投稿が出ていました。**その指示は取り消します。**",
        "",
        "  × 9月に入って、夏の記憶がすこし遠くなりました。（何の話か分からない）",
        "  ○ 福井のシンガーソングライターが、夏を1枚のアルバムにしています。",
        "",
        "80 字以内は続けます。ただし **「入りきらない分を thread に回す」のではなく、",
        "「本文で言い切れる大きさまで話を絞る」** と考えてください。",
        "**thread は補足であって、本文の続きではありません。**",
        "",
        "## 文体の要点",
        "- 丁寧で落ち着いた敬語。です・ます調",
        "- 一文は短く。3〜4 行ごとに空行",
        "- **前置きを書かない。** 「最近思うのですが」「よく言われることですが」のような入り方をしない",
        "- **心情の描写を入れない。** 「悩みました」「迷っています」「うれしかったです」は削る。",
        "  出来事と、そこから言えることだけを書く",
        "- **言い訳・保険をかけない。** 「あくまで個人的には」「人によりますが」を付けない",
        "- 絵文字は使わない。ハッシュタグは 0〜1 個",
        "- リンクは貼らない（例外は 17:00 の「福井のおでかけ情報」の枠。その枠は出典元のURLを書く）",
        "- 1 投稿につき伝えたいことは 1 つだけ",
        "- クライアント実名は出さない（「福井の解体業の会社さん」のように業種で表現する）",
        "- 金額・社内事情・未公開情報は書かない",
        "- 誇張しない、盛らない。自慢に読めないよう、学び・失敗・裏側の形で語る",
        "",
        "## 絶対に書かないこと",
        "- 金額・料金・プラン名・単価。「月◯万円」「◯円から」「初期費用」なども一切書かない。",
        "  営業資料に価格が載っていても、投稿には持ち込まない。料金の話題自体を避ける。",
        "- 電話番号・住所・担当者名などの連絡先",
        "- 契約期間、見積り、値引き、キャンペーンの条件",
        "",
        "## 事実について（最重要）",
        "確認できない事実を創作しないこと。ネタ帳・運用ボード・直近の投稿に根拠がある内容だけを書く。",
        "成果や反響（「問い合わせが増えました」など）は、根拠がない限り絶対に書かない。",
        "運用ボードやネタ帳に書かれている数字（再生数・フォロワー数など）は、",
        "そこにある値のまま使ってかまいません。丸めたり盛ったりしないこと。",
        "材料にない数字は、たとえもっともらしくても作らないこと。",
        "材料が足りなければ、材料のある範囲で小さく書く。",
        "ネタ帳の「使ってほしくないネタ」に書かれた話題は絶対に使わない。",
        "",
        "## 長さと形",
        "- **本文は 80 字以内を基本にします。** 本文だけで意味が通る大きさまで話を絞ります",
        "  （根拠: 会社アカウント @fukui._.fukui の測定 79 本で、上位 10 本のうち 9 本が",
        "  80 字以内。1 位 2819・2 位 1821・3 位 1533 はいずれも短い。",
        "  このアカウント自身のデータでは中 81〜150 字が優勢だが本数が少なく、",
        "  より大きな母数のほうを採る）",
        "- 80 字を超えるのは、1 文削ったら意味が通らなくなるときだけ",
        "- 続きは thread に回す",
        "- thread は 1〜2 件。1 件あたり 500 字以内",
        "- text も thread も 500 字を超えないこと",
        "",
        "## 出力形式",
        "JSON では返さないでください。次の形式のテキストだけを返します。",
        "前後に説明や ``` を付けないこと。",
        "",
        "@@@POST",
        "HOUR: 6",
        "NOTE: 使った柱と型とネタ",
        "TEXT:",
        "本文をここに書く。改行や空行はそのまま書いてよい。",
        "THREAD:",
        "連投の 1 件目。改行や空行はそのまま書いてよい。",
        "THREAD:",
        "連投の 2 件目。無ければこの 2 行ごと省く。",
        "@@@END",
        "",
        f"{hours} のぶんを、この順に @@@POST 〜 @@@END の組で並べてください。",
        "HOUR には 6 / 12 / 20 のいずれかの数字だけを書きます。",
    ]
    if hotel and hotel_hour is not None:
        # 5と0のつく日は、楽天トラベルのクーポンが出る（エントリー不要）。
        旅の得 = お得日.旅(target_date)
        sections += [
            f"## {hotel_hour}:00 の枠は、宿のまとめです（楽天トラベル・PR）",
            "",
            *(
                [
                    f"今日は楽天トラベルの「{旅の得['名']}」（{旅の得['何が']}）。",
                    "クーポンの案内は返信にこちらで付けるので、見出しには書かないでください。",
                    "",
                ]
                if 旅の得
                else []
            ),
            "今日並べる宿（こちらで組み立てます。あなたは見出しだけ書いてください）:",
            *[f"- {行}" for 行 in hotel["一覧"]],
            "",
            *宿の決まり(hotel),
            "",
        ]
    if not hotel and hotel_hour is None:
        sections += [
            "## 今日は宿の紹介をしません",
            "",
            "紹介できる宿が用意されていません。**どの枠でも宿の紹介を書かないでください。**",
            "宿の名前を出して良さを伝える書き方をしない。予約をすすめる書き方をしない。",
            "",
        ]
    if deal and deal_hour is not None:
        sections += [
            f"## {deal_hour}:00 の枠だけ、今日のお得日の話です（楽天市場・PR）",
            "",
            f"今日は「{deal['お得日']['名']}」（{deal['お得日']['いつ']}）。{deal['お得日']['何が']}。",
            f"条件: {deal['お得日']['条件']}",
            "",
            "この枠で並べる商品（渡したものだけ。足さないこと）:",
            *[
                f"- {x['name']}｜"
                + "・".join(
                    かけら
                    for かけら in x["memo"].split("・")
                    if "ポイント" not in かけら
                )
                for x in deal["商品"]
            ],
            "",
            "この枠の書き方には、守っていただく決まりがあります。",
            "",
            "1. **本文の冒頭を必ず「【PR】」で始める。** 末尾ではなく先頭です（ステマ規制）",
            "2. **1行目で「誰に向けた話か」をはっきり書く。**",
            "   例：「スマホで撮っている人へ」。全員に向けて書かないこと",
            "3. **倍率・割引率などの数字は書かない。** 楽天のキャンペーンは予告なく変わります。",
            "   変わった日に嘘になるので、「ポイントが増える日」までにとどめて、",
            "   くわしい条件はリンク先で見てもらってください",
            "4. **エントリーが要ることを必ず書く。**",
            "   忘れると1円も得をしません。書かないと読む人に損をさせます",
            *(
                ["5. **ゴールド会員以上が対象だと必ず書く。**",
                 "   誰でも得をする日ではありません。書かないと嘘になります"]
                if not deal["お得日"].get("誰でも", True)
                else ["5. 会員ランクの条件はありません。誰でも参加できる日です"]
            ),
            f"6. **いつまでかを書く（{deal['お得日']['期限']}）。** いま見る理由になります",
            "7. **URL は絶対に書かない。** リンクは連投（コメント欄）にこちらで付けます",
            "8. 「買うべき」と言い切らない。得なのは値段ではなくポイントです",
            "",
            "本文は【PR】を含めて日本語 60〜120 字。短いほうが読まれます。",
            "連投（リンク）はこちらで付けるので、thread は空のままにしてください。",
            "",
        ]
    return "\n".join(sections)


def parse_posts(text: str) -> list[dict]:
    """@@@POST 〜 @@@END の組を読み取る。

    JSON をやめたのは、本文に改行と空行が入るため。モデルが改行をそのまま書くと
    JSON として壊れ、投稿が 1 本も作られない日が出た。区切り記号なら改行は素通りする。
    """
    posts = []
    for body in re.findall(r"@@@POST[ \t]*\n(.*?)\n?@@@END", text, re.S):
        item = {"hour": None, "note": "", "text": "", "thread": []}
        tokens = re.split(r"^(HOUR:|NOTE:|TEXT:|THREAD:)", body, flags=re.M)
        for key, value in zip(tokens[1::2], tokens[2::2]):
            value = value.strip()
            if key == "HOUR:":
                digits = re.sub(r"\D", "", value)
                item["hour"] = int(digits) if digits else None
            elif key == "NOTE:":
                item["note"] = value
            elif key == "TEXT:":
                item["text"] = value
            elif key == "THREAD:" and value:
                item["thread"].append(value)
        if item["hour"] is not None and item["text"]:
            posts.append(item)
    return posts


def ask(api_key: str, model: str, prompt: str) -> str:
    payload = api_request(
        "POST",
        "/messages",
        api_key,
        {
            "model": model,
            "max_tokens": 8000,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    return "".join(
        block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text"
    ).strip()


def generate(api_key: str, model: str, prompt: str, expected: int) -> list[dict]:
    """1 度目で本数が揃わなければ、形式を念押しして 1 度だけやり直す。"""
    reminder = (
        "\n\n---\n直前の返答は形式が守られていませんでした。"
        "説明や ``` を付けず、@@@POST 〜 @@@END の組だけを返してください。"
    )
    for attempt in (1, 2):
        text = ask(api_key, model, prompt if attempt == 1 else prompt + reminder)
        posts = parse_posts(text)
        if len(posts) == expected:
            return posts
        print(f"::warning::{attempt} 回目: {expected} 本のはずが {len(posts)} 本でした。")
        if attempt == 2:
            fail(
                f"{expected} 本を作れませんでした（2 回試行）。\n--- 生の出力 ---\n{text[:1200]}"
            )
    return []


# 「出典元：」に書かれた URL を取り出す。
# 同じ催しを 1 日に 2 本出していないかは、この URL で見る（2026-09-23 代表指示）。
# 本文の言い回しは変えられても、出典は変えられないので、これがいちばん確かな鍵になる。
SOURCE_URL = re.compile(r"出典元[：:]\s*(https?://\S+)")


def source_urls(text: str, thread: list[str]) -> set[str]:
    found = set()
    for part in [text or "", *(thread or [])]:
        for url in SOURCE_URL.findall(part):
            found.add(url.rstrip("）)、。,. "))
    return found



# 宿の紹介枠（2026-09-23 代表指示）。楽天トラベルのアフィリエイト。
# どの宿をどの切り口で出すかは scripts/宿.py が日付から決める。
# 3アカウントとも同じリスト・同じ計算なので、同じ日には同じ内容になる。
DEAL_HOUR = 21

# 1本のまとめに何軒並べるか。
宿の軒数 = 7

HOTEL_HOUR = 17

# 【PR】の印。本文の先頭に無ければ止める（ステマ規制）。
if "PR_MARKERS" not in dir():
    PR_MARKERS = ("【PR】", "#PR", "＃PR", "[PR]")
if "URL_IN_TEXT" not in dir():
    URL_IN_TEXT = re.compile(r"https?://\S+")

# 泊まっていない宿を「泊まった」と書かせない。
# 楽天トラベルに載っている情報を読んで書くだけなので、体験として書くと嘘になる。
STAYED_VOICE = re.compile(
    r"泊まっ(た|て)|宿泊した|行ってき|訪れた|使ってみ|入ってみ|食べてき"
)


def 宿の決まり(選んだ: dict) -> list[str]:
    """宿の枠で守ってもらう決まり。

    2026-09-23、代表が見つけた「よく伸びている楽天トラベルの投稿」に合わせた。
      1本目 … 「【福井】◯◯な宿7選」＋ 宿名の一覧だけ。リンクを入れない
      返信  … 冒頭に「PR」。宿ごとに一文とリンク
    本文にリンクを入れると表示が落ちるので、リンクは返信に置く。
    一覧は保存されやすく、返信まで読んだ人がリンクを踏む、という流れ。

    AI に書いてもらうのは **1行目の見出しだけ**。
    宿の一覧・一文・リンクは、こちらがデータから組み立てる
    （宿の名前を書き間違えたり、無い宿を足したりしないため）。
    """
    return [
        "**この枠で書くのは、1行目の見出しだけです。** 他は何も書かないでください。",
        "",
        f"今日の切り口: {選んだ['name']}",
        "",
        "見出しの決まり",
        "",
        "1. **「【福井】」で始める。** そのあとに、どんな宿を集めたかを書く",
        "2. **最後に「◯選」と軒数を入れる。**",
        f"   今日は {選んだ['軒数']} 軒なので「{選んだ['軒数']}選」です",
        "3. **日本語で 30 字まで。** 1行だけ。改行しない",
        "4. **URL・【PR】・絵文字・ハッシュタグは書かない。** こちらで付けます",
        "5. **「ない」と書かない。** 楽天トラベルに載っていないのは",
        "   「設備が無い」ではなく「宿が登録していない」かもしれません",
        "6. **泊まった体で書かない。** この宿には泊まっていません",
        "",
        "例（そのまま使わず、今日の切り口に合わせて書いてください）",
        "  【福井】夜遅く着いても入れる宿7選",
        "  【福井】サウナがある宿7選",
        "  【福井】朝ごはんの場所が分かる宿7選",
        "",
        "thread は空のままにしてください。返信はこちらで付けます。",
    ]


def 宿の本文(まとめ: dict, 見出し: str) -> str:
    """1本目。見出し＋宿の一覧。リンクは入れない。

    宿の名前が長い日に上限を超えることがあるので、入らなければ下から減らす。
    見出しの「◯選」と数が食い違わないよう、数もここで直す。
    """
    宿たち = list(まとめ["宿"])
    while 宿たち:
        削り = {**まとめ, "宿": 宿たち}
        直した = 見出し.strip()
        for 数 in range(len(まとめ["宿"]), 0, -1):
            直した = 直した.replace(f"{数}選", f"{len(宿たち)}選")
        本 = 直した + "\n\n" + "\n".join(宿.一覧の行(削り))
        if リンクの長さ(本) <= リンクの上限 or len(宿たち) <= 3:
            return 本
        宿たち = 宿たち[:-1]
    return 見出し.strip()


def 宿の返信(まとめ: dict, 対象日) -> list[str]:
    """返信。冒頭に PR を置き、宿ごとの一文とリンクを並べる。

    楽天アフィリエイトの決まりでは、広告表記はファーストビューに置く。
    だから返信の1行目を「PR」にする。
    """
    行たち = 宿.返信の行(まとめ)
    頭 = "PR\n楽天トラベルのページはこちらです"
    出, いま, 先頭 = [], 頭, True
    for 行 in 行たち:
        つぎ = いま + "\n\n" + 行
        if リンクの長さ(つぎ) > リンクの上限:
            出.append(いま)
            いま = "PR\n\n" + 行
        else:
            いま = つぎ
        先頭 = False
    if いま:
        出.append(いま)

    # クーポン。代表が楽天アフィリエイトの管理画面で作ったリンクだけを使う。
    # 「5と0のつく日」のものは、その日だけ出す。
    クーポン = 宿.クーポンを読む()
    きょう旅 = お得日.旅(対象日)
    使う = [
        c for c in クーポン
        if str(c.get("いつ", "いつでも")) != "5と0のつく日" or きょう旅
    ]
    if 使う:
        塊 = ["PR", "楽天トラベルのクーポンはこちらです"]
        if きょう旅:
            塊.append("今日は5と0のつく日。エントリーは要りません")
        塊.append("")
        for c in 使う[:3]:
            塊.append(f"{c['名']}\n{c['url']}")
            塊.append("")
        出.append("\n".join(塊).strip())
    return 出


リンクの長さ = len
リンクの上限 = 480  # Threads は 500 字


# 倍率・割引率の数字。お得日の枠では書かせない（楽天のキャンペーンは変わる）。
# 商品名そのものに「P10倍」「20%OFF」が入っていることがあるので、
# 渡した商品名に含まれる分は見逃す。名前を書き写しただけで止めると、
# その日の投稿が全部できなくなってしまう。
倍率の数字 = re.compile(r"(?:ポイント|P)?\s*\d+(?:\.\d+)?\s*(?:倍|％|%|パーセント|割|割引|OFF|off|オフ)")


def あやしい倍率(text: str, deal: dict) -> str | None:
    """本文にある倍率のうち、渡した商品名に無いものを返す。"""
    名たち = " ".join(x["name"] for x in deal["商品"])
    for m in 倍率の数字.finditer(text):
        語 = m.group(0)
        if 語.replace(" ", "") in 名たち.replace(" ", ""):
            continue
        return 語
    return None


def お得日のリンク(deal: dict) -> list[str]:
    """お得日の枠のリンクを、連投にまとめる。本文には入れない。"""
    かたまり, いま = [], ""
    for x in deal["商品"]:
        行 = f"【PR】{x['name']}\n{x['url']}"
        つぎ = (いま + "\n\n" + 行) if いま else 行
        if いま and リンクの長さ(つぎ) > リンクの上限:
            かたまり.append(いま)
            いま = 行
        else:
            いま = つぎ
    if いま:
        かたまり.append(いま)
    return かたまり


def 宿のリンク(選んだ: dict) -> list[str]:
    """宿のリンクを、連投1本にまとめられるだけまとめる。

    本文にURLを入れると表示が落ちるので、リンクは連投（コメント欄）に置く。
    連投は少ないほうが読まれるので、入るだけ1本にまとめる。
    """
    かたまり, いま = [], ""
    for 行 in 選んだ.get("links") or []:
        つぎ = (いま + "\n\n" + 行) if いま else 行
        if いま and リンクの長さ(つぎ) > リンクの上限:
            かたまり.append(いま)
            いま = 行
        else:
            いま = つぎ
    if いま:
        かたまり.append(いま)
    return かたまり

def new_id(hour: int, existing: set[str]) -> str:
    stamp = datetime.now(JST).strftime("%Y%m%d")
    while True:
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
        candidate = f"p-{stamp}{hour:02d}-{suffix}"
        if candidate not in existing:
            return candidate


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        fail("ANTHROPIC_API_KEY が未設定です。リポジトリの Secrets に登録してください。")

    dry_run = os.environ.get("DRY_RUN", "").lower() == "true"
    override = os.environ.get("TARGET_DATE", "").strip()
    if override:
        try:
            target_date = datetime.strptime(override, "%Y-%m-%d").date()
        except ValueError:
            fail(f"TARGET_DATE の形式が不正です: {override}（YYYY-MM-DD で指定してください）")
    else:
        target_date = (datetime.now(JST) + timedelta(days=1)).date()
    print(f"作成対象: {target_date}（日本時間）")

    lines = read_queue_lines()
    entries = parse_entries(lines)
    existing_ids = {str(e.get("id")) for e in entries if e.get("id")}

    # すでに埋まっている枠は触らず、空いている枠だけを作る
    filled = find_filled(entries, target_date)
    needed = [slot for slot in SLOTS if slot[0] not in filled]
    # お得日じゃない日は、お得日の枠を作らない。
    if not お得日.市場(target_date):
        needed = [slot for slot in needed if slot[0] != DEAL_HOUR]
    if filled:
        print("すでに予約済みの枠: " + "、".join(f"{h}:00" for h in sorted(filled)))
    if not needed:
        print(f"{target_date} は全ての枠が埋まっています。何もしません。")
        return
    # 当日ぶんを作り直すときに、すでに時刻を過ぎた枠を作らない
    # （過ぎた時刻で作ると、次の tick で即座に投稿されてしまうため）
    now_jst = datetime.now(JST)
    past = [
        slot[0]
        for slot in needed
        if datetime(target_date.year, target_date.month, target_date.day, slot[0], tzinfo=JST) <= now_jst
    ]
    if past:
        print("すでに時刻を過ぎているため作らない枠: " + "、".join(f"{h}:00" for h in past))
        needed = [slot for slot in needed if slot[0] not in past]
        if not needed:
            print("作れる枠がありません。何もしません。")
            return

    print("これから作る枠: " + "、".join(f"{h}:00" for h, *_ in needed))

    board = fetch_doc(os.environ.get("BOARD_DOC_ID", "").strip(), "運用ボード")
    neta = read_neta()

    # 紹介枠。毎日 1 本、PR_HOUR の枠だけ。
    # どの商品を出すかは scripts/商品.py が日付から決める。
    # X と yu は同じリスト・同じ計算なので、同じ日には同じ商品になる。
    一覧 = 商品.読む()
    product = None
    if 一覧 and any(hour == PR_HOUR for hour, *_ in needed):
        選んだ = 商品.今日の商品(target_date, 一覧)
        if 選んだ:
            product = 商品.投稿用にする(選んだ)
            並び = 商品.並び(一覧)
            print(
                f"紹介枠: {PR_HOUR}:00 ｜ {product['name']}"
                f"（{len(一覧)} 件中／並びの長さ {len(並び)}）"
            )
            成績 = 選んだ.get("成績") or {}
            if 成績:
                print(
                    f"  これまで {成績.get('本数')} 本・平均閲覧 {成績.get('平均閲覧')}"
                    f"・平均反応 {成績.get('平均反応')}"
                )
            if 選んだ.get("セール"):
                print("  セール中のため、並びに多く入っています。")
    elif 一覧:
        print(f"紹介枠: {PR_HOUR}:00 はすでに埋まっているため、今回は紹介しません。")
    else:
        print("::warning::商品リストが空です。紹介枠は通常の投稿になります。")

    # お得日の枠（2026-09-23 代表指示）。お得日に当たった日だけ出る。
    # 型は「誰向け ＋ どんなお得 ＋ 期限」。代表共有のnote記事より。
    # 数字（倍率・割引率）は書かせない。楽天のキャンペーンは予告なく変わるため。
    deal = None
    きょうの得 = お得日.市場(target_date)
    if きょうの得 and 一覧 and any(hour == DEAL_HOUR for hour, *_ in needed):
        のぞく = (product or {}).get("url")
        品 = [商品.投稿用にする(x) for x in 商品.お得日の品(target_date, 一覧, のぞく=のぞく)]
        if 品:
            deal = {"お得日": きょうの得, "商品": 品}
            print(f"お得日の枠: {DEAL_HOUR}:00 ｜ {きょうの得['名']} ｜ {len(品)} 件")
    elif きょうの得:
        print(f"お得日の枠: 今日は{きょうの得['名']}ですが、枠が埋まっているか商品がありません。")

    # 宿のまとめ枠（2026-09-23 代表指示）。毎日 1 本、HOTEL_HOUR の枠だけ。
    # どの切り口で何軒並べるかは scripts/宿.py が日付から決める。
    # 3アカウントとも同じリスト・同じ計算なので、同じ日には同じ宿が並ぶ。
    宿たち = 宿.読む()
    hotel = None
    if 宿たち and any(hour == HOTEL_HOUR for hour, *_ in needed):
        まとめ = 宿.今日のまとめ(target_date, 宿たち, いくつ=宿の軒数)
        if まとめ:
            hotel = {
                "name": まとめ["切り口"]["問い"],
                "軒数": len(まとめ["宿"]),
                "一覧": 宿.一覧の行(まとめ),
                "raw": まとめ,
            }
            print(
                f"宿の枠: {HOTEL_HOUR}:00 ｜ {hotel['name']}"
                f"（{hotel['軒数']} 軒／リスト {len(宿たち)} 軒）"
            )
        else:
            print("::warning::今日は 5 軒そろう切り口がありません。宿の紹介はしません。")
    elif 宿たち:
        print(f"宿の枠: {HOTEL_HOUR}:00 はすでに埋まっているため、今回は紹介しません。")
    else:
        print("::warning::宿のリストが空です。宿の紹介はしません。")

    model = pick_model(api_key)
    prompt = build_prompt(
        board,
        neta,
        recent_texts(entries),
        target_date,
        needed,
        filled,
        product=product,
        pr_hour=PR_HOUR if product else None,
        hotel=hotel,
        hotel_hour=HOTEL_HOUR if hotel else None,
        deal=deal,
        deal_hour=DEAL_HOUR if deal else None,
    )
    posts = generate(api_key, model, prompt, len(needed))

    by_hour = {int(p["hour"]): p for p in posts}
    new_lines = []
    # その日すでにキューに入っている投稿の出典も数に入れる。
    # YU さんの指示で入れたものは例外なので、note に「指示」と書いてあれば数えない。
    出典の枠: dict[str, int] = {}
    for h, e in filled.items():
        if "指示" in str(e.get("note", "")):
            continue
        for u in source_urls(e.get("text", ""), e.get("thread") or []):
            出典の枠[u] = h

    for hour, *_ in needed:
        post = by_hour.get(hour)
        if not post:
            fail(f"{hour}:00 の投稿が返ってきませんでした。")
        text = (post.get("text") or "").strip()
        if not text:
            fail(f"{hour}:00 の本文が空です。")
        thread = [t.strip() for t in (post.get("thread") or []) if t and t.strip()]

        if not product and not hotel and not deal and text.startswith(PR_MARKERS):
            # 紹介枠が立っていないのに PR 投稿が作られた。
            # リンクが付かないので成果にならず、表示だけが残る。
            fail(
                f"{hour}:00 が【PR】で始まっていますが、紹介できる商品がありません"
                f"（先頭 30 字: {text[:30]!r}）。"
                "ネタ帳の「紹介する商品」に、まだ紹介していない商品を足してください。"
            )

        if product and hour == PR_HOUR:
            # 本文に URL が紛れ込んでいたら止める。AI に URL を書かせない方針のため。
            if URL_IN_TEXT.search(text):
                fail(f"{hour}:00 の本文に URL が入っています。この枠では本文にリンクを書きません。")
            if not text.startswith(PR_MARKERS):
                fail(
                    f"{hour}:00 の本文が【PR】で始まっていません（先頭 20 字: {text[:20]!r}）。"
                    "ステマ規制のため、冒頭の表記は必須です。"
                )
            # 楽天の検索で入れた商品に「使っている」と書かせない。
            if is_unused(product):
                found = USED_VOICE.search(text)
                if found:
                    fail(
                        f"{hour}:00 の本文に「{found.group(0)}」が入っています。"
                        f"この商品（{product['name']}）は本人がまだ使っていません。"
                        "使った体で書くと嘘になるので、未使用だと分かる書き方にしてください。"
                    )
            # リンクはネタ帳に書かれた文字列をそのまま使う。AI を通さない。
            thread = [f"【PR】{product['name']}\n{product['url']}"]

        for part in [text, *thread]:
            if len(part) > 500:
                fail(f"{hour}:00 に 500 字を超える要素があります（{len(part)} 字）。")
        if deal and hour == DEAL_HOUR:
            if URL_IN_TEXT.search(text):
                fail(f"{hour}:00 の本文に URL が入っています。この枠では本文にリンクを書きません。")
            if not text.startswith(PR_MARKERS):
                fail(
                    f"{hour}:00 の本文が【PR】で始まっていません（先頭 20 字: {text[:20]!r}）。"
                    "ステマ規制のため、冒頭の表記は必須です。"
                )
            if "エントリー" not in text:
                fail(
                    f"{hour}:00 の本文に「エントリー」が入っていません。"
                    "エントリーを忘れると1円も得しないので、必ず書いてください。"
                )
            数 = あやしい倍率(text, deal)
            if 数:
                fail(
                    f"{hour}:00 の本文に「{数}」が入っています。"
                    "楽天のキャンペーンは予告なく変わるので、倍率・割引率の数字は書きません。"
                )
            if not deal["お得日"].get("誰でも", True) and "ゴールド" not in text:
                fail(
                    f"{hour}:00 はゴールド会員以上だけが対象の日ですが、本文に書かれていません。"
                    "誰でも得をすると読めてしまうので、必ず書いてください。"
                )
            thread = お得日のリンク(deal)

        if not hotel and hour == HOTEL_HOUR and text.startswith(PR_MARKERS):
            # 宿の枠が立っていないのに PR 投稿が作られた。
            # リンクが付かないので成果にならず、表示だけが残る。
            fail(
                f"{hour}:00 が【PR】で始まっていますが、今日は紹介できる宿がありません"
                f"（先頭 30 字: {text[:30]!r}）。"
            )

        if hotel and hour == HOTEL_HOUR:
            # AI に書かせるのは見出し1行だけ。宿の一覧・リンクはこちらで組み立てる。
            見出し = text.splitlines()[0].strip() if text else ""
            if not 見出し:
                fail(f"{hour}:00 の見出しが空です。")
            if URL_IN_TEXT.search(見出し):
                fail(f"{hour}:00 の見出しに URL が入っています。")
            if 見出し.startswith(PR_MARKERS):
                fail(
                    f"{hour}:00 の見出しが【PR】で始まっています。"
                    "1本目にはリンクを入れないので、PR は返信の先頭に付けます。"
                )
            if "福井" not in 見出し:
                fail(f"{hour}:00 の見出しに「福井」が入っていません（{見出し!r}）。")
            if len(見出し) > 34:
                fail(f"{hour}:00 の見出しが長すぎます（{len(見出し)} 字）: {見出し!r}")
            泊 = STAYED_VOICE.search(見出し)
            if 泊:
                fail(
                    f"{hour}:00 の見出しに「{泊.group(0)}」が入っています。"
                    "この宿には泊まっていません。"
                )
            text = 宿の本文(hotel["raw"], 見出し)
            thread = 宿の返信(hotel["raw"], target_date)

        # 同じ催しを 1 日に 2 本出していないかを、ここで機械的に確かめる。
        # 指示だけだと読み飛ばされる。
        重なり = source_urls(text, thread) & set(出典の枠)
        if 重なり:
            どこ = "、".join(f"{h}:00" for h in sorted(出典の枠[u] for u in 重なり))
            fail(
                f"{hour}:00 が {どこ} と同じ出来事です"
                f"（出典 {sorted(重なり)[0]}）。"
                "同じ出来事は 1 日 1 本までです。別のネタを選んでください。"
            )
        for u in source_urls(text, thread):
            出典の枠[u] = hour

        item = {
            "id": new_id(hour, existing_ids),
            "text": text,
            "scheduled_at": f"{target_date.isoformat()}T{hour:02d}:00:00+09:00",
        }
        existing_ids.add(item["id"])
        if thread:
            item["thread"] = thread
        if post.get("note"):
            item["note"] = str(post["note"])[:120]
        new_lines.append(json.dumps(item, ensure_ascii=False))
        print(f"\n=== {hour}:00 ({len(text)} 字) ===\n{text}")
        for index, part in enumerate(thread, start=2):
            print(f"--- 連投 {index} ({len(part)} 字) ---\n{part}")
        if post.get("note"):
            print(f"[メモ] {post['note']}")

    if dry_run:
        print("\nDRY_RUN のため、キューには書き込みません。")
        return

    with QUEUE_PATH.open("a", encoding="utf-8") as handle:
        for line in new_lines:
            handle.write(line + "\n")
    print(f"\nキューに {len(new_lines)} 件追加しました。")


if __name__ == "__main__":
    main()
