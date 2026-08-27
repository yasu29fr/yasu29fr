#!/usr/bin/env bash
# 投稿済み記録 (state/posted.json) に変化があればコミットして push する。
# GitHub Actions の投稿ワークフローから呼ばれる。
set -euo pipefail

if [ "${DRY_RUN:-false}" = "true" ]; then
  echo "dry-run のためコミットしません。"
  exit 0
fi

if git diff --quiet -- state/posted.json; then
  echo "記録に変更なし。コミットはしません。"
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add state/posted.json
git commit -m "chore: 投稿済み記録を更新"

# Web アプリからのキュー編集と衝突しうるので、rebase してから push する
for attempt in 1 2 3 4; do
  if git pull --rebase origin "${GITHUB_REF_NAME}" && git push; then
    exit 0
  fi
  wait=$((2 ** attempt))
  echo "push に失敗。${wait} 秒待って再試行します。"
  sleep "${wait}"
done
exit 1
