# threads-bot — Threads 自動投稿の仕組み

リポジトリに置いた投稿キューを、GitHub Actions の cron が毎日 1 件ずつ Threads へ投稿します。
サーバーは不要、依存ライブラリもゼロ（Python 3.11 以上の標準ライブラリのみ）です。

```
posts/queue.jsonl  ──▶  GitHub Actions (cron)  ──▶  Threads Graph API
   投稿したい文章          未投稿の先頭を 1 件選ぶ        コンテナ作成 → 公開
                                  │
                                  └──▶ state/posted.json に記録してコミット（二重投稿の防止）
```

## 1. 使い方（日々の運用）

`posts/queue.jsonl` に 1 行 1 投稿の JSON を書き足して push するだけです。

```jsonl
{"text": "今日やったこと。"}
{"text": "予約投稿もできます。", "scheduled_at": "2026-09-01T09:00"}
{"text": "画像つき。", "image_url": "https://example.com/photo.jpg", "alt_text": "作業机の写真"}
{"text": "連投の1件目。", "thread": ["2件目は1件目への返信になります。", "3件目。"]}
```

| フィールド | 必須 | 説明 |
| --- | --- | --- |
| `text` | ○ | 本文。500 文字まで |
| `id` | | 投稿の識別子。省略時は本文から自動生成（同じ本文は同じ id になります） |
| `scheduled_at` | | 予約日時。`2026-09-01T09:00` 形式。タイムゾーン省略時は Asia/Tokyo |
| `image_url` / `video_url` | | 公開 URL のメディア。どちらか一方のみ |
| `alt_text` | | メディアの代替テキスト |
| `link_attachment` | | テキスト投稿に付けるリンク |
| `reply_control` | | `everyone` / `accounts_you_follow` / `mentioned_only` |
| `thread` | | 連投。1 件目への返信として順につながります |

投稿順のルール:

1. 投稿済み（`state/posted.json` にある id）は飛ばす
2. `scheduled_at` が現在時刻を過ぎているものを、時刻の早い順に
3. 残りを `posts/queue.jsonl` の並び順に

`scheduled_at` が未来のものは、その時刻を過ぎた最初の実行で投稿されます。cron の実行時刻は
数分ずれることがあるため、分単位の正確さが必要な用途には向きません。

投稿が終わった行はキューから消しても構いません（記録は id で持っているため、消しても
再投稿はされません）。

## 2. セットアップ

### 2.1 Meta 側でアプリとトークンを用意する

1. [Meta for Developers](https://developers.facebook.com/) でアプリを作り、ユースケースに
   **Threads API** を追加する
2. 権限に `threads_basic` と `threads_content_publish` を追加する
   （投稿枠の確認に `threads_manage_insights` もあると便利）
3. アプリに自分の Threads アカウントを連携し、短期アクセストークンを発行する
4. 短期トークンを長期トークン（60 日）に交換する:

   ```bash
   curl -s "https://graph.threads.net/access_token\
   ?grant_type=th_exchange_token\
   &client_secret=<アプリのシークレット>\
   &access_token=<短期トークン>"
   ```

5. 返ってきた `access_token` を使って、自分の user_id を確認する:

   ```bash
   THREADS_ACCESS_TOKEN=<長期トークン> PYTHONPATH=src python3 -m threads_bot me
   ```

### 2.2 GitHub Secrets を登録する

リポジトリの **Settings → Secrets and variables → Actions** で登録します。

| Secret | 内容 |
| --- | --- |
| `THREADS_USER_ID` | 上の `me` で確認した数値 ID |
| `THREADS_ACCESS_TOKEN` | 長期アクセストークン |
| `GH_PAT` | （任意）トークン自動更新用。Secrets への書き込み権限を持つ PAT |

### 2.3 投稿時刻を決める

`.github/workflows/threads-post.yml` の cron を編集します。**GitHub Actions の cron は UTC** です。

| 日本時間 | cron |
| --- | --- |
| 毎日 9:00 | `0 0 * * *` |
| 毎日 12:00 と 20:00 | `0 3,11 * * *` |
| 平日 18:00 | `0 9 * * 1-5` |

### 2.4 まず dry-run で試す

Actions タブ →「Threads 自動投稿」→ **Run workflow** で `dry_run` に ✔ を入れて実行すると、
API を呼ばずに「何が投稿されるか」だけログに出ます。問題なければ ✔ を外して本番実行します。

## 3. トークンの期限切れを防ぐ

長期トークンの有効期限は 60 日です。`Threads トークン更新` ワークフローが毎週月曜に
`refresh_access_token` を叩いて期限を延ばします。`GH_PAT` を登録していれば新しいトークンを
`THREADS_ACCESS_TOKEN` に自動で書き戻し、未登録なら警告だけ出るので手動で更新してください。

> 60 日以上まったく実行されないとトークンは失効し、2.1 からやり直しになります。
> 更新できるのは「発行から 24 時間以上経過した長期トークン」のみです。

## 4. ローカルから使う

```bash
cp .env.example .env   # 値を埋める
set -a && . ./.env && set +a

PYTHONPATH=src python3 -m threads_bot validate        # キューの形式チェック
PYTHONPATH=src python3 -m threads_bot post --dry-run  # 投稿せず内容だけ表示
PYTHONPATH=src python3 -m threads_bot post            # 1 件投稿
PYTHONPATH=src python3 -m threads_bot post --limit 3  # 3 件投稿
PYTHONPATH=src python3 -m threads_bot me              # トークンの持ち主を確認
PYTHONPATH=src python3 -m threads_bot limit           # 24 時間の投稿枠の残り
```

`pip install -e .` すれば `threads-bot post` の形でも実行できます。

## 5. 仕組みの詳細

- **投稿は 2 段階** — Threads API は `POST /{user-id}/threads` でコンテナを作り、
  `POST /{user-id}/threads_publish` で公開します。画像・動画はコンテナが `FINISHED` に
  なるまで待ってから公開します。
- **二重投稿の防止** — 投稿するとワークフローが `state/posted.json` を更新してコミットします。
  この記録が唯一の判断材料なので、手で消すと再投稿されます。
- **同時実行の防止** — ワークフローに `concurrency: threads-post` を設定し、実行が重ならない
  ようにしています。
- **再試行** — 429 と 5xx、通信エラーは指数バックオフ（2s / 4s / 8s）で 3 回まで再試行します。
  400 番台のリクエストエラーは再試行せず即座に失敗させます。
- **投稿の上限** — Threads の API 投稿は 1 アカウント 24 時間で 250 件までです
  （返信は 1,000 件）。`threads-bot limit` で残りを確認できます。

## 6. テスト

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

push と PR で同じテストが「テスト」ワークフローとして走ります。

## 7. ファイル構成

```
posts/queue.jsonl            投稿キュー（ここを編集する）
state/posted.json            投稿済みの記録（自動更新。手で触らない）
src/threads_bot/
  client.py                  Threads Graph API クライアント（再試行つき）
  queue.py                   キューの読み込みと投稿対象の選択
  poster.py                  コンテナ作成 → 公開 → 連投
  state.py                   投稿済み記録の読み書き
  config.py                  環境変数の読み込み
  cli.py                     コマンドライン
.github/workflows/
  threads-post.yml           定期投稿
  threads-refresh-token.yml  トークンの自動更新
  test.yml                   テスト
```
