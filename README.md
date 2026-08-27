# threads-bot — Threads 自動投稿の仕組み

投稿キューをリポジトリに置き、GitHub Actions の cron が時間になったものを Threads へ投稿します。
キューはブラウザの画面から編集できます。サーバーは不要、依存ライブラリもゼロ
（Python 3.11 以上の標準ライブラリのみ）です。

```
┌──────────────┐  GitHub API   ┌────────────────────┐
│ Web アプリ    │ ────────────▶ │ posts/queue.jsonl  │
│ (GitHub Pages)│               │ 投稿キュー           │
└──────────────┘               └─────────┬──────────┘
                                          │
                        ┌─────────────────┴─────────────────┐
                        │ GitHub Actions (cron)             │
                        │  15 分おき → 予約時刻が来たもの      │
                        │  毎日 9:00  → 順番待ちを 1 件       │
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

### 初回だけ必要な設定

画面右上の「設定」で GitHub の Personal Access Token を登録します。トークンは**そのブラウザの中だけ**に
保存され、GitHub API 以外のどこにも送信されません。

[Fine-grained token の作成ページ](https://github.com/settings/personal-access-tokens/new)で、

| 項目 | 設定 |
| --- | --- |
| Repository access | Only select repositories → `yasu29fr/yasu29fr` |
| Permissions → Repository → **Contents** | **Read and write** |

権限は Contents だけで足ります。

### 校正機能（任意）

本文を書いて「Claude で校正する」を押すと、誤字脱字・表記ゆれ、回りくどい言い回し、
内容に合う絵文字を見てくれます。校正案は「この文面にする」でそのまま本文に入ります。

使うには、設定に Anthropic の API キーを登録します
（[キーの作成](https://console.anthropic.com/settings/keys)）。空のままなら校正ボタンは出ません。

> **キーには利用上限を設定してください。** GitHub のトークンと違い、Anthropic の API キーは
> 「このリポジトリだけ」のような絞り込みができず、そのまま課金につながります。
> 校正専用のキーを作り、Console で上限を決めておくのが安全です。

呼び出しは `claude-opus-5`、`effort: low`。1 回あたりおよそ 1〜2 円です。

> ページ自体は公開されていますが、トークンを持っていない人には何も編集できません。
> ただしキューの中身は公開リポジトリにあるため、**予約中の投稿は誰でも読めます**。
> 公開前に伏せておきたい内容は、このリポジトリには置かないでください。

## 2. 投稿のタイミング

| 種類 | いつ投稿されるか | 対応するワークフロー |
| --- | --- | --- |
| 日時を指定した投稿 | 指定時刻を過ぎた最初の実行（15 分おきに確認） | `Threads 予約投稿` |
| 順番待ちの投稿 | 毎日 9:00 に上から 1 件 | `Threads 日次投稿` |

予約は 15 分程度の粒度で考えてください。分単位の正確さが必要な用途には向きません。

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

| ジョブ | 間隔 | `event_type` |
| --- | --- | --- |
| 予約投稿の確認 | 15 分おき | `threads-tick` |
| 順番待ちの消化 | 毎日 9:00 (JST) | `threads-drip` |

共通の設定:

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

時刻を変えたい場合は `.github/workflows/` の cron を編集します。**GitHub Actions の cron は UTC** です。

| 日本時間 | cron |
| --- | --- |
| 毎日 9:00 | `0 0 * * *` |
| 毎日 12:00 と 20:00 | `0 3,11 * * *` |
| 平日 18:00 | `0 9 * * 1-5` |

## 3. キューを直接編集する

Web アプリを使わず、`posts/queue.jsonl` に 1 行 1 投稿の JSON を書いても同じです。

```jsonl
{"text": "今日やったこと。"}
{"text": "予約投稿。", "scheduled_at": "2026-09-01T09:00"}
{"text": "画像つき。", "image_url": "https://example.com/photo.jpg", "alt_text": "作業机の写真"}
{"text": "連投の1件目。", "thread": ["2件目は1件目への返信になります。", "3件目。"]}
```

| フィールド | 必須 | 説明 |
| --- | --- | --- |
| `text` | ○ | 本文。500 文字まで |
| `id` | | 投稿の識別子。省略時は本文から自動生成 |
| `scheduled_at` | | 予約日時。`2026-09-01T09:00` 形式。タイムゾーン省略時は Asia/Tokyo |
| `image_url` / `video_url` | | 公開 URL のメディア。どちらか一方のみ |
| `alt_text` | | メディアの代替テキスト |
| `link_attachment` | | テキスト投稿に付けるリンク |
| `reply_control` | | `everyone` / `accounts_you_follow` / `mentioned_only` |
| `thread` | | 連投。1 件目への返信として順につながります |

投稿が終わった行はキューから消しても構いません（記録は id で持っているため、消しても
再投稿はされません）。

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
PYTHONPATH=src python3 -m threads_bot post               # 1 件投稿
PYTHONPATH=src python3 -m threads_bot post --scheduled-only  # 予約時刻が来たものだけ
PYTHONPATH=src python3 -m threads_bot me                 # トークンの持ち主を確認
PYTHONPATH=src python3 -m threads_bot limit              # 24 時間の投稿枠の残り
```

`pip install -e .` すれば `threads-bot post` の形でも実行できます。

## 7. 仕組みの詳細

- **投稿は 2 段階** — `POST /{user-id}/threads` でコンテナを作り、
  `POST /{user-id}/threads_publish` で公開します。画像・動画はコンテナが `FINISHED` に
  なるまで待ってから公開します。
- **二重投稿の防止** — 投稿するとワークフローが `state/posted.json` を更新してコミットします。
  この記録が唯一の判断材料なので、手で消すと再投稿されます。
- **同時実行の防止** — 予約投稿と日次投稿は同じ `concurrency: threads-post` に属し、
  同時には走りません。
- **再試行** — 429 と 5xx、通信エラーは指数バックオフ（2s / 4s / 8s）で 3 回まで再試行します。
  400 番台のリクエストエラーは再試行せず即座に失敗させます。
- **投稿の上限** — Threads の API 投稿は 1 アカウント 24 時間で 250 件までです
  （返信は 1,000 件）。`threads-bot limit` で残りを確認できます。

## 8. テスト

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

push と PR で同じテストが「テスト」ワークフローとして走ります。

## 9. ファイル構成

```
docs/                          Web アプリ（GitHub Pages で配信）
  index.html / styles.css / app.js
posts/queue.jsonl              投稿キュー
state/posted.json              投稿済みの記録（自動更新。手で触らない）
assets/images/                 Web アプリから添付した画像
src/threads_bot/
  client.py                    Threads Graph API クライアント（再試行つき）
  queue.py                     キューの読み込みと投稿対象の選択
  poster.py                    コンテナ作成 → 公開 → 連投
  state.py                     投稿済み記録の読み書き
  config.py                    環境変数の読み込み
  cli.py                       コマンドライン
scripts/commit_state.sh        投稿済み記録のコミット（ワークフロー共通）
.github/workflows/
  threads-post.yml             予約投稿（15 分おき）
  threads-drip.yml             日次投稿（毎日 9:00）
  threads-check.yml            接続確認（手動）
  threads-refresh-token.yml    トークンの自動更新
  test.yml                     テスト
```
