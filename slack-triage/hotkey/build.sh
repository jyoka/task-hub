#!/bin/sh
# hotkey/main.swift から bin/slack-triage-hotkey（Intel / Apple シリコン両対応）を作る。swiftc（Xcode の Command Line Tools）が要る。
# kiro/install.sh（11. Slackトリアージ）が使う人の Mac で実行する。bin/ はリポジトリに入れない（.gitignore）。
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out=$here/../bin/slack-triage-hotkey
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
for arch in arm64 x86_64; do
  swiftc -O -target "$arch-apple-macos12" -o "$tmp/hotkey-$arch" "$here/main.swift"
done
mkdir -p "$(dirname "$out")"
lipo -create -output "$out" "$tmp/hotkey-arm64" "$tmp/hotkey-x86_64"
codesign --force --sign - "$out"  # 署名なしだと Apple シリコンでは動かない（ad-hoc 署名）
lipo -info "$out"
