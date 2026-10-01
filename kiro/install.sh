#!/bin/sh
# kiro/install.sh: sets up task-hub on a Mac without admin rights (docs/prd-kiro-installer.md, section 5).
#   sh kiro/install.sh
# Each stage checks whether it is already done and skips it, so running this again is always safe.
# Everything goes under $HOME. What this script put there is recorded in
# ~/.local/state/task-hub/install-manifest.json, for the uninstaller.
# For tests: TASK_INSTALL_GITHUB replaces https://github.com (release downloads, the reachability check),
# TASK_INSTALL_REPO the URL that task-hub is cloned from.
set -u

GITHUB=${TASK_INSTALL_GITHUB:-https://github.com}
BIN_DIR=$HOME/.local/bin
LIB_DIR=$HOME/.local/lib/task-hub
STATE_DIR=$HOME/.local/state/task-hub
MANIFEST=$STATE_DIR/install-manifest.json
ZPROFILE_LINE='export PATH="$HOME/.local/bin:$PATH"'
# The stages, in order. Each is a function stage_<name>; later stages (kiro-cli, login, board, ...) are added here.
STAGES="prereq python gh task_hub"
# What the manifest records: "python" (the one ~/.local/bin/task uses) and, under "installed", what this script
# put there (only that: an existing gh or Python is used, not recorded). Shell variable M_<key>, "_" for "-".
MANIFEST_KEYS="uv uv_python gh task_hub task zprofile"

here=$(cd "$(dirname "$0")/.." && pwd)
orig_path=$PATH
PATH=$BIN_DIR:$PATH  # finds what an earlier run put there
export PATH
changed=

say() { printf '%s\n' "$*"; }
tilde() { case $1 in "$HOME"/*) printf '~/%s' "${1#"$HOME"/}" ;; *) printf '%s' "$1" ;; esac; }
ok() { say "$label: $1${2:+($2)}"; }  # $1: 済み / 入れました ..., $2: details
die() {  # $1: what went wrong, $2: the one thing to do next
  say "$label: 止まりました。$1"
  say "次にすること: $2"
  exit 1
}

json() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
shquote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

load_manifest() {
  M_python=
  for k in $MANIFEST_KEYS; do eval "M_$k="; done
  [ -f "$MANIFEST" ] || return 0
  M_python=$(plutil -extract python raw -o - "$MANIFEST" 2>/dev/null) || M_python=
  for k in $MANIFEST_KEYS; do
    v=$(plutil -extract "installed.$(printf %s "$k" | tr _ -)" raw -o - "$MANIFEST" 2>/dev/null) || v=
    eval "M_$k=\$v"
  done
}

write_manifest() {
  {
    printf '{\n  "version": 1,\n'
    [ -n "$M_python" ] && printf '  "python": "%s",\n' "$(json "$M_python")"
    printf '  "installed": {'
    sep=
    for k in $MANIFEST_KEYS; do
      eval "v=\$M_$k"
      [ -n "$v" ] || continue
      printf '%s\n    "%s": "%s"' "$sep" "$(printf %s "$k" | tr _ -)" "$(json "$v")"
      sep=,
    done
    printf '\n  }\n}\n'
  } > "$MANIFEST.tmp" && mv -f "$MANIFEST.tmp" "$MANIFEST" || die "$(tilde "$MANIFEST") を書けませんでした" \
    "ホームの空き容量と権限を確かめて、もう一度実行してください"
}

fetch() {  # $1: URL, $2: file
  curl -fsSL --retry 2 --connect-timeout 20 --max-time 900 -o "$2" "$1" \
    || die "ダウンロードできませんでした: $1" "ネットワーク(VPN、プロキシ)を確かめて、もう一度実行してください"
}

latest_tag() {  # $1: owner/repo. Sets TAG from where releases/latest redirects to (no API calls)
  url=$(curl -fsSIL --connect-timeout 20 --max-time 60 -o /dev/null -w '%{url_effective}' "$GITHUB/$1/releases/latest") || url=
  case $url in
    */releases/tag/?*) TAG=${url##*/} ;;
    *) die "$1 の最新の版を調べられませんでした" "ネットワーク(VPN、プロキシ)を確かめて、もう一度実行してください" ;;
  esac
}

verify() {  # $1: downloaded file, $2: checksum list ("<sha256>  <name>" lines). Stops unless they match
  name=${1##*/}
  line=$(awk -v n="$name" '{ f = $2; sub(/^\*/, "", f) } f == n { print; exit }' "$2")
  if [ -z "$line" ] || ! (cd "$(dirname "$1")" && printf '%s\n' "$line" | shasum -a 256 -c -s); then
    got=$(shasum -a 256 "$1" | awk '{ print $1 }')
    die "$name のチェックサムが合いません(一覧: ${line%% *}、実際: $got)。入れていません" \
      "時間をおいてもう一度実行してください。続くときは task-hub の担当者に知らせてください"
  fi
}

install_bin() {  # $1: file -> $BIN_DIR/$2, replaced in one step
  mkdir -p "$BIN_DIR" && cp "$1" "$BIN_DIR/.$2.tmp" && chmod 755 "$BIN_DIR/.$2.tmp" \
    && mv -f "$BIN_DIR/.$2.tmp" "$BIN_DIR/$2" \
    || die "$(tilde "$BIN_DIR/$2") に置けませんでした" "ホームの空き容量と権限を確かめて、もう一度実行してください"
}

python_ok() { [ -n "$1" ] && [ "$1" != /usr/bin/python3 ] && [ -x "$1" ] \
  && "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; }

# --- stages ---

stage_prereq() {
  label="1. 前提の確認"
  [ "$(uname -s)" = Darwin ] || die "macOS 用です(この OS: $(uname -s))" "docs/setup.md の手順で手作業で入れてください"
  case $(uname -m) in
    arm64) ARCH=arm64 ;;
    x86_64) ARCH=x86_64 ;;
    *) die "この CPU($(uname -m))には対応していません" "docs/setup.md の手順で手作業で入れてください" ;;
  esac
  # git: /usr/bin/git is a shim that opens the "install the developer tools" dialog when they are missing, so
  # look for the real one where xcode-select says the tools are, without running the shim.
  dev=$(xcode-select -p 2>/dev/null) || dev=
  if [ -z "$dev" ] || [ ! -x "$dev/usr/bin/git" ]; then
    say "$label: 止まりました。git がありません(Xcode の Command Line Tools が入っていません)。"
    say "情シスへの依頼文:"
    say "  task-hub(業務ツール)を使うため、この Mac に Xcode の Command Line Tools を入れてください"
    say "  (ターミナルで xcode-select --install。管理者権限が要る場合があります)。"
    say "  macOS $(sw_vers -productVersion 2>/dev/null)、CPU ${ARCH}、ユーザー $(id -un)"
    say "次にすること: 上の依頼文を情シスに送り、入ったらもう一度実行してください"
    exit 1
  fi
  GIT=$dev/usr/bin/git
  # Proxy: curl, git, gh, and uv read HTTPS_PROXY but not the system settings, so copy it from there.
  # A PAC file cannot be read; that only matters if GitHub is unreachable without it (below).
  # SSL_CERT_FILE is never set: gh would stop using the keychain.
  proxy= pac=
  if [ -z "${HTTPS_PROXY:-}${https_proxy:-}" ]; then
    sc=$(scutil --proxy 2>/dev/null)
    sc_get() { printf '%s\n' "$sc" | sed -n "s/^ *$1 : //p" | head -n 1; }
    if [ "$(sc_get HTTPSEnable)" = 1 ] && [ -n "$(sc_get HTTPSProxy)" ]; then
      port=$(sc_get HTTPSPort)
      HTTPS_PROXY=http://$(sc_get HTTPSProxy)${port:+:$port}
      export HTTPS_PROXY
      proxy=$HTTPS_PROXY
    elif [ "$(sc_get ProxyAutoConfigEnable)" = 1 ]; then
      pac=1
    fi
  fi
  if ! curl -fsSI --connect-timeout 20 --max-time 60 -o /dev/null "$GITHUB"; then
    if [ -n "$pac" ]; then
      die "GitHub に届きません。この Mac は自動プロキシ設定(PAC)を使っていて、インストーラはそれを読めません" \
        "情シスにプロキシのホストとポートを聞き、HTTPS_PROXY=http://ホスト:ポート sh kiro/install.sh で実行してください"
    fi
    die "GitHub($GITHUB)に届きません${proxy:+(プロキシ $proxy)}" "ネットワーク(VPN、プロキシ)を確かめて、もう一度実行してください"
  fi
  ok 済み "macOS ${ARCH}、git、GitHub に接続${proxy:+、プロキシ $proxy}"
}

stage_python() {
  label="2. Python"
  # The one an earlier run chose, if it still works: ~/.local/bin/task keeps running the same Python.
  if python_ok "$M_python"; then
    PY=$M_python
    ok 済み "$(tilde "$PY")"
    return
  fi
  for name in python3.13 python3.12 python3.11 python3.10 python3; do
    p=$(command -v "$name" 2>/dev/null) || continue
    if python_ok "$p"; then  # never /usr/bin/python3: 3.9, or the developer tools dialog
      PY=$p M_python=$p
      write_manifest
      ok "済み" "$(tilde "$PY") を使います"
      return
    fi
  done
  # None: get uv (a single binary) and let it fetch Python into the home folder.
  # Not uv's install script: it skips the checksum when sha256sum is missing, as it is on macOS.
  uv=$(command -v uv 2>/dev/null) || uv=
  if [ -z "$uv" ]; then
    say "$label: uv を取っています…"
    case $ARCH in arm64) triple=aarch64-apple-darwin ;; *) triple=x86_64-apple-darwin ;; esac
    latest_tag astral-sh/uv
    asset=uv-$triple.tar.gz
    fetch "$GITHUB/astral-sh/uv/releases/download/$TAG/$asset" "$work/$asset"
    fetch "$GITHUB/astral-sh/uv/releases/download/$TAG/$asset.sha256" "$work/$asset.sha256"
    verify "$work/$asset" "$work/$asset.sha256"
    tar -xzf "$work/$asset" -C "$work" || die "$asset を展開できませんでした" "もう一度実行してください"
    install_bin "$work/uv-$triple/uv" uv
    uv=$BIN_DIR/uv M_uv=$BIN_DIR/uv
    write_manifest
  fi
  say "$label: uv で Python 3.12 を取っています…"
  # UV_SYSTEM_CERTS: trust the keychain (a company's SSL inspection root), not only uv's own list.
  if ! UV_SYSTEM_CERTS=1 UV_PYTHON_BIN_DIR=$BIN_DIR "$uv" python install 3.12 >"$work/uv.log" 2>&1; then
    die "uv で Python を入れられませんでした($(tail -n 1 "$work/uv.log"))" \
      "ネットワーク(releases.astral.sh に届くか)を確かめて、もう一度実行してください"
  fi
  M_uv_python=3.12
  python_ok "$BIN_DIR/python3.12" || die "入れた Python($(tilde "$BIN_DIR/python3.12"))が動きません" \
    "もう一度実行してください。続くときは task-hub の担当者に知らせてください"
  PY=$BIN_DIR/python3.12 M_python=$BIN_DIR/python3.12
  write_manifest
  changed=1
  ok 入れました "uv で Python 3.12、$(tilde "$PY")"
}

stage_gh() {
  label="3. gh"
  if gh=$(command -v gh 2>/dev/null) && "$gh" --version >/dev/null 2>&1; then
    ok 済み "$(tilde "$gh")"
    return
  fi
  say "$label: GitHub CLI を取っています…"
  latest_tag cli/cli
  ver=${TAG#v}
  case $ARCH in arm64) a=arm64 ;; *) a=amd64 ;; esac
  dir=gh_${ver}_macOS_$a
  sums=gh_${ver}_checksums.txt
  fetch "$GITHUB/cli/cli/releases/download/$TAG/$dir.zip" "$work/$dir.zip"
  fetch "$GITHUB/cli/cli/releases/download/$TAG/$sums" "$work/$sums"
  verify "$work/$dir.zip" "$work/$sums"
  unzip -q -o "$work/$dir.zip" -d "$work" || die "$dir.zip を展開できませんでした" "もう一度実行してください"
  install_bin "$work/$dir/bin/gh" gh
  M_gh=$BIN_DIR/gh
  write_manifest
  "$BIN_DIR/gh" --version >/dev/null 2>&1 || die "入れた gh が動きません" \
    "情シスに、ホームの下に置いた実行ファイルを止めていないか確かめてください"
  changed=1
  ok 入れました "gh ${ver}、$(tilde "$BIN_DIR/gh")"
}

stage_task_hub() {
  label="5. task-hub 本体"
  did=
  export GIT_TERMINAL_PROMPT=0  # fail instead of waiting for a password nobody can type
  if [ -d "$LIB_DIR/.git" ]; then
    before=$("$GIT" -C "$LIB_DIR" rev-parse HEAD 2>/dev/null)
    if "$GIT" -C "$LIB_DIR" pull --ff-only -q >"$work/git.log" 2>&1; then
      [ "$before" = "$("$GIT" -C "$LIB_DIR" rev-parse HEAD 2>/dev/null)" ] || did="${did}更新、"
    else  # the copy there still works: go on with it
      say "$label: $(tilde "$LIB_DIR") を更新できませんでした($(tail -n 1 "$work/git.log"))。今の版のまま進めます"
    fi
  elif [ -e "$LIB_DIR" ]; then
    die "$(tilde "$LIB_DIR") がありますが、git の clone ではありません" "中身を確かめて別の場所に移してから、もう一度実行してください"
  else
    url=${TASK_INSTALL_REPO:-$("$GIT" -C "$here" remote get-url origin 2>/dev/null)}
    url=${url:-https://github.com/dip-ka-jo/task-hub.git}
    mkdir -p "$(dirname "$LIB_DIR")"
    "$GIT" clone -q "$url" "$LIB_DIR" >"$work/git.log" 2>&1 \
      || die "$url を clone できませんでした($(tail -n 1 "$work/git.log"))" \
        "GitHub でこのリポジトリを読めるか確かめて、もう一度実行してください"
    M_task_hub=$LIB_DIR
    write_manifest
    did="${did}clone、"
  fi

  # ~/.local/bin/task is a wrapper, not a link: bin/task's "#!/usr/bin/env python3" could find /usr/bin/python3.
  wrapper=$BIN_DIR/task
  want="#!/bin/sh
# task-hub: made by kiro/install.sh. Runs bin/task with the Python the installer checked (3.10 or later).
exec $(shquote "$PY") $(shquote "$LIB_DIR/bin/task") \"\$@\""
  if [ -L "$wrapper" ]; then  # the link from docs/setup.md's manual install is replaced; anything else is left alone
    case $(readlink "$wrapper") in
      "$LIB_DIR/bin/task") ;;
      *) die "$(tilde "$wrapper") が別のもの($(readlink "$wrapper"))を指しています" "それを消すか移してから、もう一度実行してください" ;;
    esac
  elif [ -f "$wrapper" ] && ! grep -q '^# task-hub: made by kiro/install.sh' "$wrapper"; then
    die "$(tilde "$wrapper") が既にあります(このインストーラが作ったものではありません)" "それを消すか移してから、もう一度実行してください"
  fi
  if [ -L "$wrapper" ] || [ "$(cat "$wrapper" 2>/dev/null)" != "$want" ]; then
    mkdir -p "$BIN_DIR" && printf '%s\n' "$want" > "$wrapper.tmp" && chmod 755 "$wrapper.tmp" \
      && mv -f "$wrapper.tmp" "$wrapper" || die "$(tilde "$wrapper") を書けませんでした" "ホームの空き容量と権限を確かめて、もう一度実行してください"
    did="${did}$(tilde "$wrapper")、"
  fi
  M_task=$wrapper
  write_manifest

  case ":$orig_path:" in
    *":$BIN_DIR:"*|*":$BIN_DIR/:"*) ;;
    *)
      if ! grep -qxF "$ZPROFILE_LINE" "$HOME/.zprofile" 2>/dev/null; then
        printf '\n# task-hub (kiro/install.sh)\n%s\n' "$ZPROFILE_LINE" >> "$HOME/.zprofile" \
          || die "~/.zprofile に書けませんでした" "~/.zprofile の権限を確かめて、もう一度実行してください"
        M_zprofile=$ZPROFILE_LINE
        write_manifest
        did="${did}~/.zprofile に PATH、"
      fi
      ;;
  esac

  if [ -n "$did" ]; then
    changed=1
    ok 入れました "${did%、}"
  else
    ok 済み "$(tilde "$LIB_DIR")、$(tilde "$wrapper")"
  fi
}

# --- main ---

say "task-hub をセットアップします(管理者権限は使いません)"
label="準備"
mkdir -p "$STATE_DIR" || die "$(tilde "$STATE_DIR") を作れませんでした" "ホームの権限を確かめてください"
work=$(mktemp -d "$STATE_DIR/install.XXXXXX") || die "作業用のフォルダを作れませんでした" "ホームの空き容量を確かめてください"
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
TMPDIR=$work/  # what the tools write temporarily stays in the home folder too
export TMPDIR
load_manifest
PY=

for stage in $STAGES; do
  "stage_$stage"
done

if [ -n "$changed" ]; then
  say "ここまで終わりました。"
else
  say "すべて済みです。変えたものはありません。"
fi
say "次にすること: GitHub にログインしてください(gh auth login -s project。この段階はまだインストーラにありません)"
