#!/bin/sh
# kiro/install.sh: sets up task-hub on a Mac without admin rights (docs/prd-kiro-installer.md, section 5).
#   sh kiro/install.sh [--with-launchd] [--start-launchd]
# --with-launchd: also put the launchd plist that keeps `task watch` running (stage 10). It is only started with
# --start-launchd (which implies --with-launchd), after the user said yes.
# Each stage checks whether it is already done and skips it, so running this again is always safe.
# Everything goes under $HOME. What this script put there is recorded in
# ~/.local/state/task-hub/install-manifest.json, for the uninstaller (kiro/uninstall.sh). At the end it runs
# kiro/doctor.sh, which can also be run by itself at any time.
# For tests: TASK_INSTALL_GITHUB replaces https://github.com (release downloads, the reachability check),
# TASK_INSTALL_REPO the URL that task-hub is cloned from, TASK_INSTALL_KIRO_CLI https://prod.download.cli.kiro.dev,
# TASK_INSTALL_APPLICATIONS /Applications (where an installed Kiro CLI.app is looked for).
# TASK_INSTALL_GH_LOGIN=terminal: log in to GitHub in a Terminal window from the start (see stage_gh_login).
set -u

GITHUB=${TASK_INSTALL_GITHUB:-https://github.com}
BIN_DIR=$HOME/.local/bin
LIB_DIR=$HOME/.local/lib/task-hub
STATE_DIR=$HOME/.local/state/task-hub
MANIFEST=$STATE_DIR/install-manifest.json
ZPROFILE_LINE='export PATH="$HOME/.local/bin:$PATH"'
CONFIG=$HOME/.config/task-hub/config.ini
DEVICE_URL=https://github.com/login/device
KIRO_CLI_DOWNLOAD=${TASK_INSTALL_KIRO_CLI:-https://prod.download.cli.kiro.dev}
KIRO_CLI_APP="$HOME/Applications/Kiro CLI.app"  # where this script puts Kiro CLI when there is none
KIRO_CLI_BIN="Contents/MacOS/kiro-cli"  # in the app
KIRO_CLI_TEAM=94KV3E626L  # AMZN Mobile LLC, who signs Kiro CLI.app (and Kiro.app)
KIRO_DIR=$HOME/.kiro
LAUNCHD_LABEL=com.task-hub.watch
PLIST=$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist
KEYCHAIN_SERVICE=task-hub-kiro-api-key  # docs/kiro-ide.md, section 6
MARK='task-hub: made by kiro/install.sh'
# The stages, in order. Each is a function stage_<name>.
STAGES="prereq python gh kiro_cli task_hub gh_login kiro_login board config kiro launchd"
# What the manifest records: "python" (the one ~/.local/bin/task uses) and, under "installed", what this script
# put there (only that: an existing gh or Python is used, not recorded). Shell variable M_<key>, "_" for "-".
MANIFEST_KEYS="uv uv_python gh kiro_cli kiro_cli_app task_hub task zprofile config kiro_skill_task kiro_skill_chief
  kiro_steering kiro_hook kiro_workflow kiro_settings launchd"

here=$(cd "$(dirname "$0")/.." && pwd)
orig_path=$PATH
PATH=$BIN_DIR:$PATH  # finds what an earlier run put there
export PATH
changed= todo=  # todo: what is left to do by hand, said on the last line
restart=  # stage 9 changed what Kiro reads when it starts
mounted=  # the Kiro CLI disk image, while it is attached

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

runs() { [ -x "$1" ] && "$1" --version >/dev/null 2>&1; }

stage_kiro_cli() {
  label="4. kiro-cli"
  link=$BIN_DIR/kiro-cli
  if runs "$link"; then
    ok 済み "$(tilde "$link")"
    return
  fi
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    die "$(tilde "$link") がありますが、動きません" "それを消すか移してから、もう一度実行してください"
  fi
  # One there already (a link left in ~/.local/bin that no longer works is skipped by command -v, or replaced)
  found=
  for k in "$(command -v kiro-cli 2>/dev/null)" "${TASK_INSTALL_APPLICATIONS:-/Applications}/Kiro CLI.app/$KIRO_CLI_BIN" \
    "$KIRO_CLI_APP/$KIRO_CLI_BIN"; do
    if [ -n "$k" ] && [ "$k" != "$link" ] && runs "$k"; then
      found=$k
      break
    fi
  done
  how=リンクしました
  if [ -z "$found" ]; then
    # The official install script copies the app to /Applications, which needs admin rights. This does what it
    # does, but into ~/Applications: the disk image from the official manifest, checked with its sha256.
    say "$label: Kiro CLI を取っています(公式の手順ではありません: 公式のスクリプトは管理者権限の要る /Applications に入れるため)…"
    fetch "$KIRO_CLI_DOWNLOAD/stable/latest/manifest.json" "$work/kiro-manifest.json"
    info=$("$PY" -c 'import json, sys, urllib.parse
p = next(p for p in json.load(open(sys.argv[1]))["packages"] if p["os"] == "macos" and p["fileType"] == "dmg")
print(urllib.parse.quote(p["download"]), p["sha256"], sep="\n")' "$work/kiro-manifest.json" 2>/dev/null) \
      || die "Kiro CLI の一覧(manifest.json)に macOS 用の DMG がありません" "時間をおいてもう一度実行してください。続くときは task-hub の担当者に知らせてください"
    dl=$(printf '%s\n' "$info" | sed -n 1p) sum=$(printf '%s\n' "$info" | sed -n 2p)
    dmg=$work/kiro-cli.dmg
    fetch "$KIRO_CLI_DOWNLOAD/stable/$dl" "$dmg"
    got=$(shasum -a 256 "$dmg" | awk '{ print $1 }')
    [ "$got" = "$sum" ] || die "Kiro CLI の DMG のチェックサムが合いません(一覧: ${sum}、実際: ${got})。入れていません" \
      "時間をおいてもう一度実行してください。続くときは task-hub の担当者に知らせてください"
    mkdir -p "$work/kiro-dmg"
    hdiutil attach -readonly -nobrowse -noautoopen -mountpoint "$work/kiro-dmg" "$dmg" >"$work/hdiutil.log" 2>&1 \
      || die "Kiro CLI の DMG を開けませんでした($(tail -n 1 "$work/hdiutil.log"))。入れていません" \
        "情シスに、Kiro CLI を /Applications に入れてもらってから、もう一度実行してください"
    mounted=$work/kiro-dmg
    app=$mounted/Kiro\ CLI.app
    if ! codesign --verify --deep --strict "$app" >"$work/codesign.log" 2>&1 \
      || ! codesign --verify -R="anchor apple generic and certificate leaf[subject.OU] = \"$KIRO_CLI_TEAM\"" \
        "$app/$KIRO_CLI_BIN" >>"$work/codesign.log" 2>&1; then
      die "Kiro CLI の署名を確かめられませんでした($(tail -n 1 "$work/codesign.log"))。入れていません" \
        "時間をおいてもう一度実行してください。続くときは task-hub の担当者に知らせてください"
    fi
    tmp=$HOME/Applications/.Kiro\ CLI.app.tmp
    rm -rf "$tmp"
    mkdir -p "$HOME/Applications" && ditto "$app" "$tmp" && rm -rf "$KIRO_CLI_APP" && mv "$tmp" "$KIRO_CLI_APP" \
      || die "$(tilde "$KIRO_CLI_APP") に置けませんでした" "ホームの空き容量と権限を確かめて、もう一度実行してください"
    hdiutil detach -quiet "$mounted" >/dev/null 2>&1
    mounted=
    M_kiro_cli_app=$KIRO_CLI_APP
    write_manifest
    found=$KIRO_CLI_APP/$KIRO_CLI_BIN
    runs "$found" || die "入れた kiro-cli が動きません" "情シスに、ホームの下に置いたアプリを止めていないか確かめてください"
    how="入れました"
  fi
  mkdir -p "$BIN_DIR" && ln -sfn "$found" "$link" \
    || die "$(tilde "$link") を作れませんでした" "ホームの空き容量と権限を確かめて、もう一度実行してください"
  M_kiro_cli=$link
  write_manifest
  changed=1
  if [ "$how" = 入れました ]; then
    ok "$how" "$(tilde "$KIRO_CLI_APP")、$(tilde "$link")。公式の手順ではありません"
  else
    ok "$how" "$(tilde "$link") → $(tilde "$found")"
  fi
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

gh_user() {  # sets GH_USER and GH_SCOPES from the token gh uses; fails when gh is not logged in
  r=$(gh api -i user 2>/dev/null) || return 1
  GH_SCOPES=$(printf '%s\n' "$r" | tr -d '\r' | grep -i '^x-oauth-scopes:' | sed 's/^[^:]*: *//' | head -n 1)
  GH_USER=$(printf '%s\n' "$r" | sed -n 's/^{"login":"\([^"]*\)".*/\1/p' | head -n 1)  # the body starts with it
  [ -n "$GH_USER" ]
}

device_code() { sed -n 's/.*\([A-Z0-9]\{4\}-[A-Z0-9]\{4\}\).*/\1/p' "$1" 2>/dev/null | head -n 1; }

open_terminal() {  # $1: file name, rest: the command. Writes it to a .command file and opens that in Terminal
  file=$STATE_DIR/$1
  shift
  { printf '#!/bin/sh\n# task-hub: made by kiro/install.sh. Runs this in a Terminal window, where it can ask its questions.\n'
    sep=
    for a in "$@"; do printf '%s%s' "$sep" "$(shquote "$a")"; sep=' '; done
    printf '\necho\necho "終わったら、このウィンドウを閉じて、もう一度 kiro/install.sh を実行してください"\n'
  } > "$file" && chmod 755 "$file" || die "$(tilde "$file") を書けませんでした" "ホームの空き容量と権限を確かめて、もう一度実行してください"
  open "$file" >/dev/null 2>&1 || die "ターミナルを開けませんでした" "Finder で $(tilde "$file") をダブルクリックして進め、終わったらもう一度実行してください"
}

stage_gh_login() {
  label="6. GitHub のログイン"
  pidfile=$STATE_DIR/gh-login.pid log=$STATE_DIR/gh-login.log
  GH_USER= GH_SCOPES=
  if gh_user && case ", $GH_SCOPES," in *", project,"*) true ;; *) false ;; esac; then
    rm -f "$pidfile" "$log" "$STATE_DIR/gh-login.command"
    # git (task-hub's clones and pushes) uses the same login; non-interactive `gh auth login` does not set that up
    if "$GIT" config --global --get-all credential.https://github.com.helper 2>/dev/null | grep -q 'auth git-credential'; then
      ok 済み "$GH_USER"
      return
    fi
    gh auth setup-git -h github.com >"$work/gh.log" 2>&1 \
      || die "git に GitHub のログインを設定できませんでした($(tail -n 1 "$work/gh.log"))" "もう一度実行してください"
    changed=1
    ok 設定しました "${GH_USER}、git も gh のログインを使います"
    return
  fi
  if [ -n "$GH_USER" ]; then
    set -- auth refresh -h github.com -s project
    need="Projects の権限(project)が要ります"
  else
    set -- auth login --web -s project -h github.com -p https
    need="GitHub にログインしていません"
  fi
  if [ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then  # gh refuses to log in while one is set
    die "${need}。環境変数 GH_TOKEN(または GITHUB_TOKEN)があるので、gh ではログインできません" \
      "その環境変数を外すか、project の権限があるトークンにしてから、もう一度実行してください"
  fi
  pid=$(cat "$pidfile" 2>/dev/null) || pid=
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then  # the login an earlier run started is still waiting
    die "${need}。ブラウザでの承認を待っています" "$DEVICE_URL でコード $(device_code "$log") を入れて承認してから、もう一度実行してください"
  fi
  gh=$(command -v gh)
  if [ -n "$pid" ] || [ "${TASK_INSTALL_GH_LOGIN:-}" = terminal ]; then
    # The login an earlier run left waiting in the background is gone without logging in: it timed out, or it was
    # stopped when the command that ran this script ended. Log in in a Terminal window instead.
    open_terminal gh-login.command "$gh" "$@"
    die "${need}。開いたターミナルで、案内に沿ってブラウザで承認してください" "承認が終わったら、もう一度実行してください"
  fi
  # Without a terminal, gh prints a one-time code, then waits (up to 15 minutes) until it is entered in the browser.
  # It runs in a session of its own so that it outlives this script, and the next run checks whether it got through.
  TMPDIR=$STATE_DIR/ "$PY" -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$gh" "$@" \
    </dev/null >"$log" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" > "$pidfile"
  i=0 code=
  while [ "$i" -lt 60 ]; do
    code=$(device_code "$log")
    [ -n "$code" ] && break
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
    i=$((i + 1))
  done
  if [ -z "$code" ]; then
    kill "$pid" 2>/dev/null
    rm -f "$pidfile"
    die "gh のログインを始められませんでした($(tail -n 1 "$log"))" "ネットワーク(VPN、プロキシ)を確かめて、もう一度実行してください"
  fi
  open "$DEVICE_URL" >/dev/null 2>&1
  die "${need}。ブラウザで $DEVICE_URL を開きました。コード $code を入れて承認してください" "承認が終わったら、もう一度実行してください"
}

stage_kiro_login() {
  label="6. kiro-cli のログイン"
  if ! kiro=$(command -v kiro-cli 2>/dev/null); then
    ok 飛ばしました "kiro-cli が見つかりません。Kiro IDE だけで使う範囲は進めます"
    return
  fi
  if "$kiro" whoami </dev/null >/dev/null 2>&1; then
    rm -f "$STATE_DIR/kiro-login.command"
    ok 済み
    return
  fi
  # Not in the background as gh's: kiro-cli login first asks how to log in, in a menu that needs a terminal.
  open_terminal kiro-login.command "$kiro" login
  die "kiro-cli にログインしていません。開いたターミナルで、ログインの方法を選んでブラウザで承認してください" \
    "ログインが終わったら、もう一度実行してください"
}

helper() {  # kiro/install-board: the board, config.ini, and Kiro's settings.json, where JSON and INI are easier in Python
  "$PY" "$here/kiro/install-board" "$@"
  case $? in
    0) ;;
    3) changed=1 ;;
    1) exit 1 ;;  # it said why and what to do next
    *) die "思わぬエラーで終わりました" "task-hub の担当者に知らせてください" ;;
  esac
  [ -s "$work/todo" ] && todo=$(cat "$work/todo")
  return 0
}

stage_board() {
  label="7. ボード"
  helper board "$label" "$GH_USER" "$work"
}

stage_config() {
  label="8. 設定"
  new=
  [ -e "$CONFIG" ] || new=1
  helper config "$label" "$work"
  if [ -n "$new" ] && [ -f "$CONFIG" ]; then
    M_config=$CONFIG
    write_manifest
  fi
}

real() { "$PY" -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }

link_into() {  # $1: in the clone, $2: the link Kiro reads, $3: manifest key. Adds to $did, or to $kept
  [ -e "$1" ] || die "$(tilde "$1") がありません" "task-hub を更新できているか確かめて、もう一度実行してください"
  if [ -e "$2" ]; then
    if [ "$(real "$2")" = "$(real "$1")" ]; then  # also through another link (docs/setup.md's ~/.agents/skills)
      eval "M_$3=\$2"
    else  # someone's own (another checkout of task-hub, say)
      kept="${kept}$(tilde "$2")、"
    fi
    return
  fi
  mkdir -p "$(dirname "$2")" && ln -sfn "$1" "$2" \
    || die "$(tilde "$2") を作れませんでした" "ホームの空き容量と権限を確かめて、もう一度実行してください"
  eval "M_$3=\$2"
  did="${did}$(tilde "$2")(リンク)、"
}

copy_into() {  # $1: in the clone, $2: the copy Kiro reads, $3: manifest key. Adds to $did
  [ -f "$1" ] || die "$(tilde "$1") がありません" "task-hub を更新できているか確かめて、もう一度実行してください"
  eval "M_$3=\$2"
  [ ! -L "$2" ] && [ -f "$2" ] && cmp -s "$1" "$2" && return 0
  how=コピー
  [ -e "$2" ] || [ -L "$2" ] && how=コピーし直し  # changed by a pull, or the link of an earlier manual install
  tmp=$(dirname "$2")/.${2##*/}.tmp
  mkdir -p "$(dirname "$2")" && cp "$1" "$tmp" && mv -f "$tmp" "$2" \
    || die "$(tilde "$2") に置けませんでした" "ホームの空き容量と権限を確かめて、もう一度実行してください"
  did="${did}$(tilde "$2")(${how})、"
}

stage_kiro() {
  label="9. Kiro との連携"
  did= kept=
  # Kiro reads skills and steering through links, but not hooks and workflows: its extension reads only plain
  # files there, and checks the allowed folders with the real path (Kiro IDE 1.2.4, 2026-10-02). So those are
  # copies, made again whenever the clone's differ (after a pull).
  link_into "$LIB_DIR/skills/task" "$KIRO_DIR/skills/task" kiro_skill_task
  link_into "$LIB_DIR/skills/chief" "$KIRO_DIR/skills/chief" kiro_skill_chief
  link_into "$LIB_DIR/kiro/steering/task-hub.md" "$KIRO_DIR/steering/task-hub.md" kiro_steering
  copy_into "$LIB_DIR/kiro/hooks/task-hub-events.json" "$KIRO_DIR/hooks/task-hub-events.json" kiro_hook
  copy_into "$LIB_DIR/kiro/workflows/task-hub-events.workflow.json" "$KIRO_DIR/workflows/task-hub-events.workflow.json" \
    kiro_workflow
  write_manifest
  rm -f "$work/kiro-settings"
  c0=$changed
  helper kiro-settings "$label" "$work"
  changed=$c0
  tab=$(printf '\t')
  IFS=$tab read -r kind what < "$work/kiro-settings"
  case $kind in
    changed)
      did="${did}${what}、"
      M_kiro_settings=$(sed -n 2p "$work/kiro-settings")
      write_manifest
      ;;
    manual) kept_note=$what ;;
  esac
  if [ -n "$did" ]; then
    changed=1 restart=1
    detail="${did%、}。Kiro を再起動すると読み込まれます"
  else
    detail="スキル、steering、フック、ワークフロー、Workflows の設定"
  fi
  [ -n "$kept" ] && detail="${detail}。${kept%、} は別のものを指しているので、そのままにしました"
  [ "$kind" = manual ] && detail="${detail}。${kept_note}"
  if [ -n "$did" ]; then ok 入れました "$detail"; else ok 済み "$detail"; fi
}

xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

stage_launchd() {
  label="10. 常駐"
  if [ -z "$with_launchd" ]; then
    ok 飛ばしました "任意です。task watch を launchd で動かすときは --with-launchd を付けて実行します"
    return
  fi
  # docs/setup.md and docs/kiro-ide.md (section 6). launchd gives no login shell PATH: ~/.local/bin (task, and
  # kiro-cli and gh when this script put them there), where kiro-cli and gh are (also behind the link: the app's
  # folder, where kiro-cli's own helpers are), and the system's.
  path=$BIN_DIR
  for c in kiro-cli gh; do
    c=$(command -v "$c")
    for d in "$(dirname "$c")" "$(dirname "$( [ -L "$c" ] && readlink "$c" || echo "$c")")"; do
      case ":$path:" in *":$d:"*) ;; *) path=$path:$d ;; esac
    done
  done
  path=$path:/usr/bin:/bin:/usr/sbin:/sbin
  # KIRO_API_KEY: read from the keychain when task watch starts, never written in the plist. Without a key there,
  # kiro-cli uses its login.
  if security find-generic-password -s "$KEYCHAIN_SERVICE" >/dev/null 2>&1; then
    run="KIRO_API_KEY=\$(/usr/bin/security find-generic-password -s $KEYCHAIN_SERVICE -w) || { echo \"task-hub: no $KEYCHAIN_SERVICE in the keychain\" >&2; exit 1; }; export KIRO_API_KEY; exec $(shquote "$BIN_DIR/task") watch"
    args="    <string>/bin/sh</string>
    <string>-c</string>
    <string>$(xml "$run")</string>"
    key="KIRO_API_KEY はキーチェーンから読みます"
  else
    args="    <string>$(xml "$BIN_DIR/task")</string>
    <string>watch</string>"
    key="KIRO_API_KEY は使いません(使うなら docs/kiro-ide.md の 6 章のとおりキーチェーンに入れ、もう一度 --with-launchd で実行します)"
  fi
  want="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<!-- $MARK (docs/setup.md). Runs task watch while you are logged in. -->
<plist version=\"1.0\">
<dict>
  <key>Label</key>
  <string>$LAUNCHD_LABEL</string>
  <key>ProgramArguments</key>
  <array>
$args
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$(xml "$path")</string>
    <key>HOME</key>
    <string>$(xml "$HOME")</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$(xml "$STATE_DIR/watch.out.log")</string>
  <key>StandardErrorPath</key>
  <string>$(xml "$STATE_DIR/watch.err.log")</string>
</dict>
</plist>"
  if [ -e "$PLIST" ] && ! grep -qF "$MARK" "$PLIST"; then
    die "$(tilde "$PLIST") が既にあります(このインストーラが作ったものではありません)" \
      "それを使い続けるなら --with-launchd を付けずに実行してください。インストーラのものにするなら、それを移してから、もう一度実行してください"
  fi
  wrote=
  if [ "$(cat "$PLIST" 2>/dev/null)" != "$want" ]; then
    printf '%s\n' "$want" > "$work/plist" && plutil -lint -s "$work/plist" >/dev/null \
      && mkdir -p "$(dirname "$PLIST")" && mv -f "$work/plist" "$PLIST" \
      || die "$(tilde "$PLIST") を書けませんでした" "ホームの空き容量と権限を確かめて、もう一度実行してください"
    wrote=1 changed=1
  fi
  M_launchd=$PLIST
  write_manifest
  # Starting it (launchctl bootstrap) only when the user said yes: --start-launchd
  domain=gui/$(id -u)
  loaded=
  stale=$STATE_DIR/launchd-stale  # the plist changed since the running one was started
  if launchctl print "$domain/$LAUNCHD_LABEL" >/dev/null 2>&1; then
    loaded=1
    [ -z "$wrote" ] || : > "$stale"
  else
    rm -f "$stale"
  fi
  if [ -n "$loaded" ] && [ ! -e "$stale" ]; then
    ok 済み "$(tilde "$PLIST")、動いています。${key}"
    return
  fi
  if [ -z "$start_launchd" ]; then
    ask="常駐を始めてよければ、sh kiro/install.sh --start-launchd を実行してください(ログインしている間 task watch が動き、Ready のカードを始めます)"
    state=まだ始めていません
    if [ -n "$loaded" ]; then
      ask="常駐に変えた設定を読み込ませてよければ、sh kiro/install.sh --start-launchd を実行してください(動いている task watch を起動し直します)"
      state="動いているのは変える前の設定です"
    fi
    [ -n "$todo" ] || todo=$ask
    ok "$([ -n "$wrote" ] && echo 置きました || echo 済み)" "$(tilde "$PLIST")、${state}。${key}"
    return
  fi
  [ -n "$loaded" ] && launchctl bootout "$domain/$LAUNCHD_LABEL" >/dev/null 2>&1
  i=0
  until launchctl bootstrap "$domain" "$PLIST" >"$work/launchctl.log" 2>&1; do
    i=$((i + 1))
    [ "$i" -lt 5 ] || die "launchd に登録できませんでした($(tail -n 1 "$work/launchctl.log"))" \
      "時間をおいて、もう一度 sh kiro/install.sh --start-launchd を実行してください"
    sleep 1  # bootout ends the old one in the background
  done
  rm -f "$stale"
  changed=1
  ok 始めました "$(tilde "$PLIST")、ログは $(tilde "$STATE_DIR")/watch.err.log。${key}"
}

# --- main ---

label="準備"
with_launchd= start_launchd=
for a in "$@"; do
  case $a in
    --with-launchd) with_launchd=1 ;;
    --start-launchd) with_launchd=1 start_launchd=1 ;;
    *) die "知らない引数です: $a" "sh kiro/install.sh(常駐も入れるなら --with-launchd を付けて)で実行してください" ;;
  esac
done
say "task-hub をセットアップします(管理者権限は使いません)"
mkdir -p "$STATE_DIR" || die "$(tilde "$STATE_DIR") を作れませんでした" "ホームの権限を確かめてください"
work=$(mktemp -d "$STATE_DIR/install.XXXXXX") || die "作業用のフォルダを作れませんでした" "ホームの空き容量を確かめてください"
trap '[ -z "$mounted" ] || hdiutil detach -quiet "$mounted" >/dev/null 2>&1; rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
TMPDIR=$work/  # what the tools write temporarily stays in the home folder too
export TMPDIR
load_manifest
PY=

for stage in $STAGES; do
  "stage_$stage"
done

# 11. the diagnosis: the list only; the one next step is said below
doctor_ok=1
PATH=$orig_path sh "$here/kiro/doctor.sh" --in-install || doctor_ok=  # the PATH it was run with: is ~/.local/bin on it

if [ -n "$changed" ]; then
  say "ここまで終わりました。"
else
  say "すべて済みです。変えたものはありません。"
fi
if [ -n "$todo" ]; then
  say "次にすること: $todo"
elif [ -z "$doctor_ok" ]; then
  say "次にすること: 診断の × の行の → のとおりにしてください"
elif [ -n "$restart" ]; then
  say "次にすること: Kiro を再起動し(開いているチャットには、少なくともウィンドウの再読み込みが要ります)、新しいチャットで /task を試してください"
else
  say "次にすること: Kiro の新しいチャットで /task を試してください"
fi
