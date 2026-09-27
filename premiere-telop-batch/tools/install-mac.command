#!/bin/bash
# テロップ一括調整 — macOS 用インストーラ（ダブルクリックで実行できます）
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/Library/Application Support/Adobe/CEP/extensions/com.yasu29fr.telopbatch"

# 署名なし拡張機能を読み込めるようにする（CEP 9〜12 = Premiere 2019〜2026 あたり）
for v in 9 10 11 12 13; do
  defaults write "com.adobe.CSXS.$v" PlayerDebugMode 1
done

rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$SRC/CSXS" "$SRC/css" "$SRC/js" "$SRC/jsx" "$SRC/index.html" "$SRC/.debug" "$DEST/"

echo "インストールしました: $DEST"
echo "Premiere Pro を再起動し、[ウィンドウ] > [エクステンション] > [テロップ一括調整] を開いてください。"
