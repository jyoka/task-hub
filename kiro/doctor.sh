#!/bin/sh
# kiro/doctor.sh: checks every stage of kiro/install.sh and lists what is missing, with what to do next
# (docs/prd-kiro-installer.md, section 5, stage 11). It changes nothing: no file, no login, nothing on GitHub.
#   sh kiro/doctor.sh [--in-install]
# --in-install: kiro/install.sh runs it at its end; then only the list, the installer says the one next step.
# Exit status: 0 = everything there, 1 = something missing.
# For tests: TASK_INSTALL_GITHUB replaces https://github.com (the reachability check).
set -u

GITHUB=${TASK_INSTALL_GITHUB:-https://github.com}
BIN_DIR=$HOME/.local/bin
LIB_DIR=$HOME/.local/lib/task-hub
STATE_DIR=$HOME/.local/state/task-hub
MANIFEST=$STATE_DIR/install-manifest.json
ZPROFILE_LINE='export PATH="$HOME/.local/bin:$PATH"'
KIRO_DIR=$HOME/.kiro
LAUNCHD_LABEL=com.task-hub.watch
PLIST=$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist
INSTALL="sh kiro/install.sh を実行してください(Kiro のチャットなら「セットアップして」)"

here=$(cd "$(dirname "$0")/.." && pwd)
orig_path=$PATH
PATH=$BIN_DIR:$PATH  # what the installer put there
export PATH
in_install=
for a in "$@"; do
  case $a in
    --in-install) in_install=1 ;;
    *) echo "知らない引数です: $a"; echo "次にすること: sh kiro/doctor.sh で実行してください"; exit 1 ;;
  esac
done

missing=0 first_step=
tilde() { case $1 in "$HOME"/*) printf '~/%s' "${1#"$HOME"/}" ;; *) printf '%s' "$1" ;; esac; }
ok() { printf '○ %s: %s\n' "$label" "$1"; }
ng() {  # $1: what is missing, $2: what to do next
  printf '× %s: %s\n' "$label" "$1"
  printf '    → %s\n' "$2"
  missing=$((missing + 1))
  [ -n "$first_step" ] || first_step=$2
}
python_ok() { [ -n "$1" ] && [ "$1" != /usr/bin/python3 ] && [ -x "$1" ] \
  && "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; }
runs() { [ -x "$1" ] && "$1" --version >/dev/null 2>&1; }
helper() {  # $1: board | config | kiro-settings, $2: before the detail when it is ok
  # kiro/install-board check prints "ok<TAB>detail" or "ng<TAB>detail<TAB>next"
  tab=$(printf '\t')
  IFS=$tab read -r r detail step <<EOF
$("$PY" "$here/kiro/install-board" check "$1" 2>&1)
EOF
  if [ "$r" = ok ]; then ok "${2:-}$detail"; else ng "${detail:-確かめられませんでした}" "${step:-この出力を task-hub の担当者に知らせてください}"; fi
}

[ -n "$in_install" ] && echo "診断:" || echo "task-hub の診断です(何も変えません)"

# 1. prerequisites
label="1. 前提の確認"
GIT=
dev=$(xcode-select -p 2>/dev/null) || dev=
[ -n "$dev" ] && [ -x "$dev/usr/bin/git" ] && GIT=$dev/usr/bin/git
if [ -z "${HTTPS_PROXY:-}${https_proxy:-}" ]; then  # as kiro/install.sh: the system's HTTPS proxy, if any
  sc=$(scutil --proxy 2>/dev/null)
  sc_get() { printf '%s\n' "$sc" | sed -n "s/^ *$1 : //p" | head -n 1; }
  if [ "$(sc_get HTTPSEnable)" = 1 ] && [ -n "$(sc_get HTTPSProxy)" ]; then
    port=$(sc_get HTTPSPort)
    HTTPS_PROXY=http://$(sc_get HTTPSProxy)${port:+:$port}
    export HTTPS_PROXY
  fi
fi
if [ "$(uname -s)" != Darwin ]; then
  ng "macOS ではありません($(uname -s))" "docs/setup.md の手順で手作業で入れてください"
elif [ -z "$GIT" ]; then
  ng "git がありません(Xcode の Command Line Tools が入っていません)" \
    "情シスに Command Line Tools を入れてもらってください(依頼文は sh kiro/install.sh が出します)"
elif ! curl -fsSI --connect-timeout 20 --max-time 60 -o /dev/null "$GITHUB"; then
  ng "GitHub($GITHUB)に届きません" "ネットワーク(VPN、プロキシ)を確かめてください"
else
  ok "macOS $(uname -m)、git、GitHub に接続"
fi

# 2. Python: the one the manifest says ~/.local/bin/task runs, else one the installer would choose
label="2. Python"
PY=
M_python=$(plutil -extract python raw -o - "$MANIFEST" 2>/dev/null) || M_python=
if python_ok "$M_python"; then
  PY=$M_python
else
  for name in python3.13 python3.12 python3.11 python3.10 python3; do
    p=$(command -v "$name" 2>/dev/null) || continue
    if python_ok "$p"; then PY=$p; break; fi
  done
fi
if [ -n "$PY" ]; then ok "$(tilde "$PY")"; else ng "Python 3.10 以上がありません" "$INSTALL"; fi

# 3. gh
label="3. gh"
if gh=$(command -v gh 2>/dev/null) && "$gh" --version >/dev/null 2>&1; then ok "$(tilde "$gh")"; else gh=; ng "gh がありません" "$INSTALL"; fi

# 4. kiro-cli
label="4. kiro-cli"
if runs "$BIN_DIR/kiro-cli"; then ok "$(tilde "$BIN_DIR/kiro-cli")"; else ng "$(tilde "$BIN_DIR/kiro-cli") がないか、動きません" "$INSTALL"; fi

# 5. task-hub itself
label="5. task-hub 本体"
wrapper=$BIN_DIR/task
if [ ! -d "$LIB_DIR/.git" ]; then
  ng "$(tilde "$LIB_DIR") がありません" "$INSTALL"
elif [ -L "$wrapper" ] || ! grep -q '^# task-hub: made by kiro/install.sh' "$wrapper" 2>/dev/null; then
  ng "$(tilde "$wrapper") がないか、インストーラのものではありません" "$INSTALL"
elif ! "$wrapper" --version >/dev/null 2>&1; then
  ng "$(tilde "$wrapper") が動きません" "$INSTALL"
else
  case ":$orig_path:" in
    *":$BIN_DIR:"*|*":$BIN_DIR/:"*) ok "$(tilde "$LIB_DIR")、$(tilde "$wrapper")" ;;
    *)
      if grep -qxF "$ZPROFILE_LINE" "$HOME/.zprofile" 2>/dev/null; then
        ok "$(tilde "$LIB_DIR")、$(tilde "$wrapper")、~/.zprofile に PATH"
      else
        ng "$(tilde "$BIN_DIR") が PATH にありません" "$INSTALL"
      fi
      ;;
  esac
fi

# 6. logins
label="6. GitHub のログイン"
gh_ok=
if [ -z "$gh" ]; then
  ng "gh がないので確かめていません" "$INSTALL"
elif ! r=$(gh api -i user 2>/dev/null); then
  ng "GitHub にログインしていません" "sh kiro/install.sh を実行し、案内どおりにブラウザでログインしてください"
else
  scopes=$(printf '%s\n' "$r" | tr -d '\r' | grep -i '^x-oauth-scopes:' | sed 's/^[^:]*: *//' | head -n 1)
  user=$(printf '%s\n' "$r" | sed -n 's/^{"login":"\([^"]*\)".*/\1/p' | head -n 1)
  case ", $scopes," in
    *", project,"*)
      if [ -n "$GIT" ] && "$GIT" config --global --get-all credential.https://github.com.helper 2>/dev/null \
        | grep -q 'auth git-credential'; then
        gh_ok=1
        ok "$user"
      else
        ng "${user}。git が gh のログインを使っていません" "$INSTALL"
      fi
      ;;
    *) ng "${user}。Projects の権限(project)がありません" "sh kiro/install.sh を実行し、案内どおりにブラウザで承認してください" ;;
  esac
fi
label="6. kiro-cli のログイン"
if ! kiro=$(command -v kiro-cli 2>/dev/null); then
  ng "kiro-cli がないので確かめていません" "$INSTALL"
elif "$kiro" whoami </dev/null >/dev/null 2>&1; then
  ok "ログイン済み"
else
  ng "kiro-cli にログインしていません" "sh kiro/install.sh を実行し、開いたターミナルでログインしてください"
fi

# 7, 8. the board and config.ini (kiro/install-board check: read-only)
label="7. ボード"
if [ -z "$PY" ]; then ng "Python がないので確かめていません" "$INSTALL"
elif [ -z "$gh_ok" ]; then ng "GitHub にログインできていないので確かめていません" "$INSTALL"
else helper board
fi
label="8. 設定"
if [ -z "$PY" ]; then ng "Python がないので確かめていません" "$INSTALL"; else helper config; fi

# 9. Kiro: links to the clone for skills and steering, copies the same as the clone's for the hook and the workflow
label="9. Kiro との連携"
lacks= stale= other=
same() { if [ -d "$1" ]; then [ "$(cd -P "$1" && pwd)" = "$(cd -P "$2" 2>/dev/null && pwd)" ]; else cmp -s "$1" "$2"; fi; }
for x in skills/task:skills/task skills/chief:skills/chief kiro/steering/task-hub.md:steering/task-hub.md; do
  src=$LIB_DIR/${x%%:*} dst=$KIRO_DIR/${x#*:}
  if [ ! -e "$dst" ]; then lacks="${lacks}$(tilde "$dst")、"
  elif ! same "$dst" "$src"; then other="${other}$(tilde "$dst")、"  # someone's own: the installer keeps it too
  fi
done
for x in kiro/hooks/task-hub-events.json:hooks/task-hub-events.json \
  kiro/workflows/task-hub-events.workflow.json:workflows/task-hub-events.workflow.json; do
  src=$LIB_DIR/${x%%:*} dst=$KIRO_DIR/${x#*:}
  if [ ! -f "$dst" ] || [ -L "$dst" ]; then lacks="${lacks}$(tilde "$dst")、"
  elif ! cmp -s "$src" "$dst"; then stale="${stale}$(tilde "$dst")、"
  fi
done
if [ -n "$lacks" ]; then
  ng "${lacks%、} がありません" "$INSTALL"
elif [ -n "$stale" ]; then
  ng "${stale%、} が task-hub の今の版と違います" "$INSTALL"
elif [ -z "$PY" ]; then
  ng "Python がないので Workflows の設定を確かめていません" "$INSTALL"
else
  helper kiro-settings "スキル、steering、フック、ワークフロー、"
  [ "$r" = ok ] && [ -n "$other" ] && printf '    (%s は別のものを指しています。インストーラもそのままにします)\n' "${other%、}"
fi

# 10. launchd (optional)
label="10. 常駐"
if [ ! -e "$PLIST" ]; then
  ok "使っていません(任意。使うなら sh kiro/install.sh --with-launchd)"
elif [ -e "$STATE_DIR/launchd-stale" ]; then
  ng "動いているのは変える前の設定です" "sh kiro/install.sh --start-launchd を実行してください"
elif launchctl print "gui/$(id -u)/$LAUNCHD_LABEL" >/dev/null 2>&1; then
  ok "$(tilde "$PLIST")、動いています"
else
  ng "$(tilde "$PLIST") はありますが、動いていません" "常駐を始めてよければ、sh kiro/install.sh --start-launchd を実行してください"
fi

[ -n "$in_install" ] && exit $((missing > 0))
if [ "$missing" -eq 0 ]; then
  echo "すべて揃っています。"
  echo "次にすること: Kiro の新しいチャットで /task を試してください"
  exit 0
fi
echo "足りないものが ${missing} つあります。"
echo "次にすること: $first_step"
exit 1
