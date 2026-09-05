# threads-bot — Threads 自動投稿の仕組み

投稿キューをリポジトリに置き、予約した時刻が来たものを GitHub Actions が Threads へ投稿します。
キューはブラウザの画面から編集できます。サーバーは不要、依存ライブラリもゼロ
（Python 3.11 以上の標準ライブラリのみ）です。

```
┌──────────────┐  GitHub API   ┌────────────────────┐
│ Web アプリ    │ ────────────▶ │ posts/queue.jsonl  │
│ (GitHub Pages)│               │ 投稿キュー           │
└──────────────┘               └─────────┬──────────┘
                                          │
                        ┌─────────────────┴─────────────────┐
                        │ GitHub Actions                    │
                        │ 外部 cron が数分おきに起動し、       │
                        │ 予約時刻が来たものを投稿する          │
                        └─────────────────┬─────────────────┘
                                          ▼
                                   Threads Graph API
                                          │
                          state/posted.json に記録してコミット
                                （二重投稿の防止）
```

## 1. Web アプリで予約する

**https://yasu29fr.github.io/yasu29fr/**

本文を書いて日時を選び、「キューに入れる」を押すと `posts/queue.jsonl` が更新されます。
スマホからも使えます。できることは次のとおりです。

- 予約投稿の作成・編集・複製・削除
- 連投（1件目への返信として順につながる）
- 画像の添付（リポジトリの `assets/images/` に保存され、その公開 URL を Threads に渡します）
- 投稿済みの履歴表示（Threads へのリンク付き）
- Claude による校正（誤字脱字・表記ゆれ、読みやすさ、絵文字の提案）
- ネタから複数本の投稿を作り、間隔を空けてまとめて予約
- 書きかけの自動保存（画面を閉じても、再読み込みしても消えない）
- ネタの記録（日時つきで Google ドキュメントに書き足す）— **いまは止めています**（後述）

### 初回だけ必要な設定

画面右上の「設定」で GitHub の Personal Access Token を登録します。トークンは**そのブラウザの中だけ**に
保存され、GitHub API 以外のどこにも送信されません。

[Fine-grained token の作成ページ](https://github.com/settings/personal-access-tokens/new)で、

| 項目 | 設定 |
| --- | --- |
| Repository access | Only select repositories → `yasu29fr/yasu29fr` |
| Permissions → Repository → **Contents** | **Read and write** |

権限は Contents だけで足ります。

### ネタから作る（任意）

「ネタから作る」タブに話したいことをそのまま書いて **Claude で分ける** を押すと、
独立して読める投稿に分かれます。本数は 2〜5 本から選べます。

できた投稿は**その場で直せます**。要らない本は「外す」で除けます。
1 本ずつ **校正** もかけられます。押した本だけを Claude が読み、校正案を出します。
「この文面にする」で反映、「閉じる」でそのまま。押していない本は呼び出されないので、
必要なところだけに費用がかかります。

1 本目の日時と間隔（30 分 / 1 時間 / 3 時間 / 1 日）を決めて
**まとめて予約する** を押すと、間隔をずらして一度に登録されます。

Claude の出力をそのまま登録せず、必ず確認を挟む作りにしています。
公開されるのは予約時刻が来てからなので、登録後でも「予約中」タブから直せます。

分割時の指示は次のようにしてあります。

- 書き手の言葉づかいを活かす。別人の文章にしない
- ネタに書かれていない事実を足さない
- 1 本ずつ独立して読める。「①」「続く」のような連番や引きは付けない
- 1 本 100〜200 字を目安に、500 字以内
- ネタが薄いときは、無理に指定の本数まで薄めない

### ネタの記録（いまは止めています）

> **現在この機能は使っていません。** 設定の「ネタ帳の記録先 URL / 合言葉」を空にしてあるため、
> 画面右上の **記録** ボタンは出ません。コードは消していないので、下の設定を入れ直せばすぐ戻ります。
>
> ただし**ネタ帳そのものは今も使っています**。「翌日ぶんを自動で作る」が `NETA_DOC_ID` の
> ドキュメントを読んで投稿の材料にしているためです。止めたのは「画面から書き足す」側だけで、
> 「ドキュメントを読む」側は動いています。ネタはいまのところ Google ドキュメントに直接書いています。

以下は、再開するときの手順です。

画面右上の **記録** から、思いついたことをその場で書き留められます。日時が自動で付き、
Google ドキュメントの「ネタ帳」に書き足されます。投稿を考えるときの材料になります。

静的ページから Google ドキュメントへは直接書き込めないため、Google Apps Script を
中継役にします。GCP プロジェクトや OAuth の設定は要りません。

**1. スクリプトを作る**

[script.google.com](https://script.google.com/) で新しいプロジェクトを作り、
`scripts/notes.gs` の中身をそのまま貼り付けます。先頭の 2 か所だけ書き換えてください。

| 変数 | 中身 |
| --- | --- |
| `DOC_ID` | ドキュメント URL の `/d/` と `/edit` のあいだの文字列 |
| `SECRET` | 好きな合言葉。画面の設定に入れるものと同じにする |

**2. Web アプリとして公開する**

右上の **デプロイ → 新しいデプロイ** → 種類に **ウェブアプリ** を選び、

| 項目 | 設定 |
| --- | --- |
| 次のユーザーとして実行 | 自分 |
| アクセスできるユーザー | 全員 |

「全員」にしますが、合言葉が合わなければ何も書き込めず、読み出しもできません。
発行された `https://script.google.com/macros/s/.../exec` をコピーします。

**3. 画面の設定に入れる**

設定の「ネタ帳の記録先 URL」と「ネタ帳の合言葉」に入れて保存します。
両方そろうと右上に **記録** ボタンが出ます。

> 追記先は「書き方のヒント」の見出しの**直前**です。末尾に足すと
> 「使ってほしくないネタ」の下に入ってしまうため、位置を決め打ちしています。
> ドキュメントの見出しを変えるときは `scripts/notes.gs` の `INSERT_BEFORE` も直してください。

記録に失敗したときは、書いた内容を画面に残したままエラーを表示します。

### 書きかけは消えません

入力中の内容は、少し間を置いて自動的にそのブラウザへ控えられます。画面を閉じても、
再読み込みしても、次に開いたときにそのまま戻ります。開いていたタブも復元します。

戻るのは投稿フォームの全項目（本文・日時・連投・リンク・返信設定）と、
「ネタから作る」の入力および分割結果です。**分割結果も残るので、
再読み込みのたびに Claude を呼び直すことはありません。**

キューに保存したとき、または「編集をやめる」を押したときに控えは消えます。

### 編集中は見た目が変わります

予約中の投稿を「編集」で開いているあいだは、次の 4 つが変わります。
新規の投稿だと思って書き進めてしまわないようにするためです。

- フォームの先頭に「編集中」の帯が出て、どの投稿を直しているかを日時で示す
- フォームの枠が強調される
- 「投稿を作る」タブに印が付く（別のタブにいても分かる）
- 保存ボタンが「保存する」になる

帯の「やめる」を押すと新規作成に戻ります。

> 選択した画像ファイルだけは持ち越せません（ブラウザの制約）。
> 画像を選んだ状態で再読み込みすると、その旨を伝えたうえで選び直しになります。

### 校正機能（任意）

本文を書いて「Claude で校正する」を押すと、誤字脱字・表記ゆれ、回りくどい言い回し、
内容に合う絵文字を見てくれます。校正案は「この文面にする」でそのまま本文に入ります。

使うには、設定に Anthropic の API キーを登録します
（[キーの作成](https://console.anthropic.com/settings/keys)）。空のままなら校正ボタンは出ません。

> **キーには利用上限を設定してください。** GitHub のトークンと違い、Anthropic の API キーは
> 「このリポジトリだけ」のような絞り込みができず、そのまま課金につながります。
> 校正専用のキーを作り、Console で上限を決めておくのが安全です。

校正・分割とも `claude-opus-5`、`effort: low` で呼びます。1 回あたりおよそ 1〜3 円です。

> ページ自体は公開されていますが、トークンを持っていない人には何も編集できません。
> ただしキューの中身は公開リポジトリにあるため、**予約中の投稿は誰でも読めます**。
> 公開前に伏せておきたい内容は、このリポジトリには置かないでください。

## 2. 投稿のタイミング

投稿は**予約した日時が来たときだけ**行われます。外部の cron が定期的にワークフローを
起動し、そのとき予約時刻を過ぎているものを投稿します。

起動の間隔がそのまま「遅れの上限」になります。10 分おきに起動していれば、
指定時刻から最大 10 分遅れて投稿されます。予約時刻が来たものしか出ないため、
**間隔を短くしても投稿が増えることはありません**。

予約の選択肢も 10 分刻みなので、起動が `:00 / :10 / :20 …` に揃っていれば、
選んだ時刻とほぼ同時に投稿されます。

> 予約時刻のない項目は投稿されません。`threads-bot validate` がそうした項目を
> エラーとして報告します（画面でも赤字で警告します）。

### 翌日ぶんを自動で作る

`Threads 翌日ぶんを作成` ワークフローが、運用ボードとネタ帳を材料に翌日の 3 本
（6:00 / 12:00 / 20:00）を書き、キューに追加します。外部 cron から毎日 20:00 (JST) に
`threads-compose` で起動します。

**埋まっている枠には手を出しません。** 自分で 12:00 のぶんを入れてあれば、6:00 と 20:00 の
2 本だけを作ります。3 枠とも埋まっていれば何もせずに終わります。二重に入ることはありません。

**必要な設定**

| 場所 | 名前 | 中身 |
| --- | --- | --- |
| Secrets | `ANTHROPIC_API_KEY` | Anthropic の API キー |
| Variables | `BOARD_DOC_ID` | 運用ボードの Google ドキュメント ID |
| Variables | `NETA_DOC_ID` | ネタ帳の Google ドキュメント ID |
| Variables | `ANTHROPIC_MODEL` | （任意）使うモデル。未指定なら自動で選ぶ |
| Variables | `ANTHROPIC_WORKSPACE_ID` | identity-linked な API キーを使う場合は必須 |

ドキュメント ID は秘密ではないので Variables に置きます
（Settings → Secrets and variables → Actions → **Variables** タブ）。

> **API キーの種類に注意。** identity-linked（個人ひも付き）のキーは、リクエストに
> ワークスペース ID を添える必要があります。`400 anthropic-workspace-id is required`
> が出たら、Variables に `ANTHROPIC_WORKSPACE_ID` を足すか、Console で通常の
> API キーを作って Secrets を差し替えてください。

> **2 つのドキュメントは「リンクを知っている全員が閲覧可」にしてください。**
> 認証なしの公開 URL から読むため、共有されていないと材料なしで書き始めてしまいます。
> 初回は `workflow_dispatch` の `dry_run: true` で実行し、ログに
> 「運用ボード: ◯◯ 文字を読み込みました」と出ることを確かめてください。

### 起動は外部の cron から行う

**GitHub Actions の `schedule` は当てになりません。** このリポジトリでは一度も発火しませんでした
（設定に不備はなく、手動実行は正常）。GitHub 自身も遅延・スキップがあり得ると明記しています。

そのため、外部の無料 cron から GitHub API を叩いてワークフローを起動します。
ワークフロー側は `repository_dispatch` を受け口として用意済みです（`schedule` も保険として残しています）。

**1. 起動用のトークンを作る**

[Fine-grained token を作成](https://github.com/settings/personal-access-tokens/new)し、
`yasu29fr/yasu29fr` だけに絞って **Contents: Read and write** を付けます
（`repository_dispatch` はこの権限で叩けます）。画面用とは別のトークンにしてください。

**2. cron サービスに 2 つのジョブを登録する**

[cron-job.org](https://console.cron-job.org/) などで、次の POST を登録します。

登録するジョブは 2 つです。

| ジョブ | 間隔 | `event_type` |
| --- | --- | --- |
| 予約投稿の確認 | 10 分おき | `threads-tick` |
| 翌日ぶんの作成 | 毎日 20:00 (JST) | `threads-compose` |

設定:

```
URL    : https://api.github.com/repos/yasu29fr/yasu29fr/dispatches
Method : POST
Headers: Accept: application/vnd.github+json
         Authorization: Bearer <上で作ったトークン>
         X-GitHub-Api-Version: 2022-11-28
         Content-Type: application/json
Body   : {"event_type": "threads-tick"}
```

動作確認は手元からでもできます。

```bash
curl -X POST https://api.github.com/repos/yasu29fr/yasu29fr/dispatches \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer <トークン>" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -d '{"event_type": "threads-tick"}'
```

204 が返り、Actions に `Threads 予約投稿` の実行が現れれば成功です。

> `repository_dispatch` も `schedule` と同じくデフォルトブランチのワークフローが動きます。

**起動の時刻や間隔を変えるのは cron-job.org 側です。** リポジトリ内の cron は投稿時刻に
関係しません。残っているのは次の 2 つだけです。

| 場所 | cron | 役割 |
| --- | --- | --- |
| `threads-post.yml` | `*/10 * * * *` | 外部 cron が止まったときの保険。発火しない前提で置いてある |
| `threads-refresh-token.yml` | `0 3 * * 1` | 毎週月曜 12:00 (JST) のトークン更新 |

書き換えるときは **GitHub Actions の cron は UTC** であることに注意してください
（日本時間から 9 時間引く。例: 毎日 9:00 JST → `0 0 * * *`）。

## 3. キューを直接編集する

Web アプリを使わず、`posts/queue.jsonl` に 1 行 1 投稿の JSON を書いても同じです。

```jsonl
{"text": "予約投稿。", "scheduled_at": "2026-09-01T09:00"}
{"text": "画像つき。", "scheduled_at": "2026-09-01T12:00", "image_url": "https://example.com/photo.jpg", "alt_text": "作業机の写真"}
{"text": "連投の1件目。", "scheduled_at": "2026-09-01T20:00", "thread": ["2件目は1件目への返信になります。", "3件目。"]}
```

`scheduled_at` のない行は投稿されません。`threads-bot validate` がエラーにするので、
ワークフローもそこで止まります。

| フィールド | 必須 | 説明 |
| --- | --- | --- |
| `text` | ○ | 本文。500 文字まで |
| `scheduled_at` | ○ | 予約日時。`2026-09-01T09:00` 形式。タイムゾーン省略時は Asia/Tokyo |
| `id` | | 投稿の識別子。省略時は本文から自動生成 |
| `image_url` / `video_url` | | 公開 URL のメディア。どちらか一方のみ |
| `alt_text` | | メディアの代替テキスト |
| `link_attachment` | | テキスト投稿に付けるリンク |
| `reply_control` | | `everyone` / `accounts_you_follow` / `mentioned_only` |
| `thread` | | 連投。1 件目への返信として順につながります |

**投稿が終わった行も消さずに残してください。** 消しても再投稿はされません（投稿済みの記録は
`state/posted.json` が id で持っています）が、Web アプリの「投稿済み」タブは本文をキューから
引いているため、行を消すと履歴が「(本文はキューから削除されています)」になります。

## 4. セットアップ

### 4.1 Meta 側でアプリとトークンを用意する

1. [Meta for Developers](https://developers.facebook.com/) でアプリを作り、ユースケースに
   **Threads API** を追加する
2. 権限に `threads_basic` と `threads_content_publish` を追加する
3. アプリに自分の Threads アカウントを連携し、短期アクセストークンを発行する
4. 短期トークンを長期トークン（60 日）に交換する:

   ```bash
   curl -s "https://graph.threads.net/access_token\
   ?grant_type=th_exchange_token\
   &client_secret=<アプリのシークレット>\
   &access_token=<短期トークン>"
   ```

5. 返ってきた `access_token` で自分の user_id を確認する:

   ```bash
   THREADS_ACCESS_TOKEN=<長期トークン> PYTHONPATH=src python3 -m threads_bot me
   ```

### 4.2 GitHub Secrets を登録する

**Settings → Secrets and variables → Actions**

| Secret | 内容 |
| --- | --- |
| `THREADS_USER_ID` | 上の `me` で確認した数値 ID |
| `THREADS_ACCESS_TOKEN` | 長期アクセストークン |
| `GH_PAT` | （任意）トークン自動更新用。Secrets への書き込み権限を持つ PAT |

登録できたら、Actions から **Threads 接続確認** を実行してください。投稿せずに、
トークン・user_id・投稿枠の残りだけを確認します。

### 4.3 GitHub Pages を有効にする

**Settings → Pages → Source: Deploy from a branch** で、ブランチを選び **フォルダに `/docs`**
を指定します。数分後に `https://<owner>.github.io/<repo>/` で画面が開きます。

## 5. トークンの期限切れを防ぐ

長期トークンの有効期限は 60 日です。`Threads トークン更新` ワークフローが毎週月曜に
期限を延ばします。`GH_PAT` を登録していれば新しいトークンを `THREADS_ACCESS_TOKEN` に
自動で書き戻し、未登録なら警告だけ出るので手動で更新してください。

> 60 日以上まったく実行されないとトークンは失効し、4.1 からやり直しになります。
> 更新できるのは「発行から 24 時間以上経過した長期トークン」のみです。

## 6. コマンドラインから使う

```bash
cp .env.example .env   # 値を埋める
set -a && . ./.env && set +a

PYTHONPATH=src python3 -m threads_bot validate           # キューの形式チェック
PYTHONPATH=src python3 -m threads_bot post --dry-run     # 投稿せず内容だけ表示
PYTHONPATH=src python3 -m threads_bot post               # 予約時刻が来たものを 1 件投稿
PYTHONPATH=src python3 -m threads_bot me                 # トークンの持ち主を確認
PYTHONPATH=src python3 -m threads_bot limit              # 24 時間の投稿枠の残り
PYTHONPATH=src python3 -m threads_bot refresh-token      # 長期トークンの期限を延ばす
```

`pip install -e .` すれば `threads-bot post` の形でも実行できます。

## 7. 仕組みの詳細

- **投稿は 2 段階** — `POST /{user-id}/threads` でコンテナを作り、
  `POST /{user-id}/threads_publish` で公開します。画像・動画はコンテナが `FINISHED` に
  なるまで待ってから公開します。
- **二重投稿の防止** — 投稿するとワークフローが `state/posted.json` を更新してコミットします。
  この記録が唯一の判断材料なので、手で消すと再投稿されます。
- **同時実行の防止** — `concurrency: threads-post` により、実行が重なりません。
  起動が短い間隔で重なっても、前の実行が終わるまで次は待ちます。
- **再試行** — 429 と 5xx、通信エラーは指数バックオフ（2s / 4s / 8s）で 3 回まで再試行します。
  400 番台のリクエストエラーは再試行せず即座に失敗させます。
- **投稿の上限** — Threads の API 投稿は 1 アカウント 24 時間で 250 件までです
  （返信は 1,000 件）。`threads-bot limit` で残りを確認できます。

## 8. テスト

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

push と PR で同じテストが「テスト」ワークフローとして走ります。

## 9. 他の人が同じものを作れるようにする

配布用の一式は、別の非公開リポジトリ **`yasu29fr/threads-bot-kit`** に移しました。
3 段階に分けてあり、第 1 段階（ブラウザから予約 → 自動投稿）だけで単体で完結します。

AI にコードを書かせず、完成品を ZIP で渡して「展開・検証・案内」だけをさせる作りに
してあります。渡し方と手引きは、そちらの `README.md` を見てください。

> **このリポジトリは public です。** 配布物をここに置くと、履歴ごと誰でも取得できる
> 状態になります。そのため配布用の一式は非公開側にだけ置き、こちらには戻しません。

> 配布物に含めるコードは、このリポジトリのコピーです。本体を直したときは、
> `threads-bot-kit` 側の `sync.sh` を実行して取り込み直してください。

## 10. ファイル構成

```
docs/                          Web アプリ（GitHub Pages で配信）
  index.html / styles.css / app.js
posts/queue.jsonl              投稿キュー（投稿済みの行も履歴表示のために残す）
state/posted.json              投稿済みの記録（自動更新。手で触らない）
assets/images/                 Web アプリから添付した画像
src/threads_bot/
  client.py                    Threads Graph API クライアント（再試行つき）
  queue.py                     キューの読み込みと投稿対象の選択
  poster.py                    コンテナ作成 → 公開 → 連投
  state.py                     投稿済み記録の読み書き
  config.py                    環境変数の読み込み
  cli.py                       コマンドライン
scripts/commit_file.sh         変更のあったファイルのコミット（ワークフロー共通）
scripts/compose.py             翌日ぶんの 3 本を作る
scripts/notes.gs               ネタ帳の中継役（Google Apps Script に貼る。いまは未使用）
tests/                         ユニットテスト（test.yml が実行）
.env.example                   手元で CLI を動かすときの環境変数の雛形
pyproject.toml                 パッケージ定義（`pip install -e .` 用。依存ライブラリなし）
.github/workflows/
  threads-post.yml             予約投稿（外部 cron から起動）
  threads-compose.yml          翌日ぶんの作成（外部 cron から起動）
  threads-check.yml            接続確認（手動）
  threads-refresh-token.yml    トークンの自動更新
  test.yml                     テスト
```

`scripts/notes.gs` だけは現在どこからも呼ばれていません。「ネタの記録」を再開するときに
そのまま使うため残しています。それ以外のファイルはすべて動いている経路の一部です。
