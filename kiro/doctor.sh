#!/bin/sh
# kiro/doctor.sh: checks every stage of kiro/install.sh and lists what is missing, with what to do next
# (docs/prd-kiro-installer.md, section 5, stage 11). It changes nothing: no file, no login, nothing on GitHub.
#   sh kiro/doctor.sh [--in-install]
# --in-install: kiro/install.sh runs it at its end; then only the list, the installer says the one next step.
# It judges whether task-hub works, not whether it has the installer's form: a manual install (docs/setup.md: the
# link ~/.local/bin/task, a kiro-cli on PATH, git logged in another way) that works is ○, with a note under it.
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
note() { printf '    (%s)\n' "$1"; }
ng() {  # $1: what is missing, $2: what to do next
  printf '× %s: %s\n' "$label" "$1"
  printf '    → %s\n' "$2"
  missing=$((missing + 1))
  [ -n "$first_step" ] || first_step=$2
}
python_ok() { [ -n "$1" ] && [ "$1" != /usr/bin/python3 ] && [ -x "$1" ] \
  && "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; }
runs() { [ -x "$1" ] && "$1" --version >/dev/null 2>&1; }
resolve() {  # $1: a path, with its links followed (the folders above as they are named, for tilde)
  f=$1 n=0
  while [ -L "$f" ] && [ "$n" -lt 20 ]; do
    t=$(readlink "$f") n=$((n + 1))
    case $t in /*) f=$t ;; *) f=$(dirname "$f")/$t ;; esac
  done
  d=$(cd "$(dirname "$f")" 2>/dev/null && pwd) && printf '%s/%s' "$d" "$(basename "$f")"
}
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

# task-hub's clone: the installer's, or the one ~/.local/bin/task links to (docs/setup.md, by hand)
clone=$LIB_DIR by_hand=
if [ -L "$BIN_DIR/task" ] && t=$(resolve "$BIN_DIR/task"); then
  case $t in */bin/task) [ -d "${t%/bin/task}/.git" ] && clone=${t%/bin/task} by_hand=1 ;; esac
fi

# 4. kiro-cli: the installer's link, else one on PATH that runs
label="4. kiro-cli"
if runs "$BIN_DIR/kiro-cli"; then
  ok "$(tilde "$BIN_DIR/kiro-cli")"
elif k=$(PATH=$orig_path; command -v kiro-cli 2>/dev/null) && runs "$k"; then
  ok "$(tilde "$k")"
  note "手で入れた構成です。$(tilde "$BIN_DIR/kiro-cli") はなく、PATH にあるものを使います"
else
  ng "$(tilde "$BIN_DIR/kiro-cli") がないか、動きません" "$INSTALL"
fi

# 5. logins
label="5. GitHub のログイン"
gh_ok=  # gh is logged in with project: the board can be checked
if [ -z "$gh" ]; then
  ng "gh がないので確かめていません" "$INSTALL"
elif ! r=$(gh api -i user 2>/dev/null); then
  ng "GitHub にログインしていません" "sh kiro/install.sh を実行し、案内どおりにブラウザでログインしてください"
else
  scopes=$(printf '%s\n' "$r" | tr -d '\r' | grep -i '^x-oauth-scopes:' | sed 's/^[^:]*: *//' | head -n 1)
  user=$(printf '%s\n' "$r" | sed -n 's/^{"login":"\([^"]*\)".*/\1/p' | head -n 1)
  case ", $scopes," in
    *", project,"*)
      gh_ok=1
      # git: gh's login (the installer's), else any login that reaches a private repo: the board's, or task-hub's
      repo=$(sed -n '/^[[:space:]]*\[board\]/,/^[[:space:]]*\[/s/^[[:space:]]*issues[[:space:]]*[=:][[:space:]]*\([^;# ]*\).*/\1/p' \
        "$HOME/.config/task-hub/config.ini" 2>/dev/null | head -n 1)
      if [ -n "$repo" ]; then
        url=$GITHUB/$repo.git
      else
        url=
        [ -z "$GIT" ] || url=$("$GIT" -C "$clone" remote get-url origin 2>/dev/null) || url=
        repo=$url
      fi
      if [ -n "$GIT" ] && "$GIT" config --global --get-all credential.https://github.com.helper 2>/dev/null \
        | grep -q 'auth git-credential'; then
        ok "$user"
      elif [ -n "$GIT" ] && [ -n "$url" ] \
        && GIT_TERMINAL_PROMPT=0 "$GIT" ls-remote --heads "$url" </dev/null >/dev/null 2>&1; then
        ok "$user"
        note "手で入れた構成です。git は gh 以外のログインで ${repo} に届きます"
      else
        ng "${user}。git が gh のログインを使っておらず、${repo:-GitHub の private リポジトリ} に届きません" "$INSTALL"
      fi
      ;;
    *) ng "${user}。Projects の権限(project)がありません" "sh kiro/install.sh を実行し、案内どおりにブラウザで承認してください" ;;
  esac
fi
label="5. kiro-cli のログイン"
if ! kiro=$(command -v kiro-cli 2>/dev/null); then
  ng "kiro-cli がないので確かめていません" "$INSTALL"
elif "$kiro" whoami </dev/null >/dev/null 2>&1; then
  ok "ログイン済み"
else
  ng "kiro-cli にログインしていません" "sh kiro/install.sh を実行し、開いたターミナルでログインしてください"
fi

# 6. task-hub itself
label="6. task-hub 本体"
wrapper=$BIN_DIR/task
task_py=  # by hand: the Python of bin/task's #! line
if [ -n "$by_hand" ]; then
  case $(head -n 1 "$clone/bin/task" 2>/dev/null) in
    '#!/usr/bin/env '*) task_py=$(command -v "$(head -n 1 "$clone/bin/task" | sed 's|^#!/usr/bin/env *||; s| .*||')" 2>/dev/null) ;;
    '#!'*) task_py=$(head -n 1 "$clone/bin/task" | sed 's|^#! *||; s| .*||') ;;
  esac
fi
if [ ! -d "$clone/.git" ]; then
  ng "$(tilde "$clone") がありません" "$INSTALL"
elif [ -n "$by_hand" ] && ! python_ok "$task_py"; then
  ng "$(tilde "$wrapper") の Python(${task_py:-見つかりません})が 3.10 以上ではありません" "$INSTALL"
elif [ -z "$by_hand" ] && { [ -L "$wrapper" ] || ! grep -q '^# task-hub: made by kiro/install.sh' "$wrapper" 2>/dev/null; }; then
  ng "$(tilde "$wrapper") がないか、インストーラのものではありません" "$INSTALL"
elif ! "$wrapper" --version >/dev/null 2>&1; then
  ng "$(tilde "$wrapper") が動きません" "$INSTALL"
else
  # the version, and whether there is a newer kiro-v* (as kiro/install.sh decides: its clone, in the manifest or not
  # on a branch, follows the newest kiro-v*; a clone on a branch made by hand is only pulled). ls-remote: no fetch
  lib=$(tilde "$clone") note=
  if [ -n "$GIT" ]; then
    g() { GIT_TERMINAL_PROMPT=0 "$GIT" -C "$clone" "$@"; }
    kiro_newest() { grep -E '^kiro-v[0-9]+$' | sort -t v -k 2,2n | tail -n 1; }
    M_task_hub=$(plutil -extract installed.task-hub raw -o - "$MANIFEST" 2>/dev/null) || M_task_hub=
    current=
    if branch=$(g symbolic-ref -q --short HEAD 2>/dev/null); then
      ver="$branch $(g rev-parse --short HEAD 2>/dev/null)"
    else
      branch= current=$(g tag --points-at HEAD 2>/dev/null | kiro_newest)
      ver=$current
      [ -n "$ver" ] || ver=$(g describe --tags --exact-match HEAD 2>/dev/null) || ver=$(g rev-parse --short HEAD 2>/dev/null)
    fi
    if [ -z "$M_task_hub" ] && [ -n "$branch" ]; then
      note="ブランチ $branch の上の clone です。インストーラはタグに切り替えず、pull だけします"
    elif ! remote=$(g ls-remote --tags origin 'kiro-v*' 2>/dev/null); then
      note="新しい版があるかは確かめられませんでした(origin に届きません)"
    else
      newest=$(printf '%s\n' "$remote" | sed 's|.*refs/tags/||' | kiro_newest)
      if [ -z "$newest" ]; then :
      elif [ -n "$current" ]; then
        if [ "${newest#kiro-v}" -gt "${current#kiro-v}" ]; then note="新しい版 $newest があります。$INSTALL"
        else ver="${ver}、最新"
        fi
      else  # not on a kiro-v* tag (--ref): by commits, the newest tag's (its ^{} line, if annotated) and HEAD
        sha=$(printf '%s\n' "$remote" | awk -v t="refs/tags/$newest" '$2 == t || $2 == t "^{}" { s = $1 } END { print s }')
        if ! g cat-file -e "$sha^{commit}" 2>/dev/null; then
          note="新しい版があるかは確かめられませんでした($newest のコミットが手元にありません)"
        elif ! g merge-base --is-ancestor "$sha" HEAD 2>/dev/null; then
          note="新しい版 $newest があります。$INSTALL"
        else  # --ref is for that run only: the next install goes back to the newest tag
          if [ -n "$branch" ]; then at="$branch($(g rev-parse --short HEAD 2>/dev/null))" ref=$branch
          else at=$ver ref=$(g describe --tags --exact-match HEAD 2>/dev/null) || ref=
          fi
          if [ "$(g rev-parse HEAD 2>/dev/null)" = "$sha" ]; then note="配布版 $newest と同じコミットの $at です"
          else note="配布版 $newest より新しい $at です"
          fi
          note="${note}。次にインストーラを実行すると $newest に戻ります${ref:+($ref を続けるなら --ref $ref)}"
        fi
      fi
    fi
    lib="$lib($ver)"
  fi
  case ":$orig_path:" in
    *":$BIN_DIR:"*|*":$BIN_DIR/:"*) ok "${lib}、$(tilde "$wrapper")" ;;
    *)
      if grep -qxF "$ZPROFILE_LINE" "$HOME/.zprofile" 2>/dev/null; then
        ok "${lib}、$(tilde "$wrapper")、~/.zprofile に PATH"
      else
        ng "$(tilde "$BIN_DIR") が PATH にありません" "$INSTALL"
      fi
      ;;
  esac
  [ -z "$by_hand" ] || note "手で入れた構成です。$(tilde "$wrapper") は clone の bin/task へのリンクで、インストーラの wrapper ではありません"
  [ -z "$note" ] || note "$note"
fi

# 7, 8. the board and config.ini (kiro/install-board check: read-only). The board needs only gh, not git
label="7. ボード"
if [ -z "$PY" ]; then ng "Python がないので確かめていません" "$INSTALL"
elif [ -z "$gh_ok" ]; then ng "gh が Projects の権限でログインできていないので確かめていません" "$INSTALL"
else helper board
fi
label="8. 設定"
if [ -z "$PY" ]; then ng "Python がないので確かめていません" "$INSTALL"; else helper config; fi

# 9. Kiro: links to the clone for skills and steering, copies the same as the clone's for the hook and the workflow
# (a copy that differs only in the description, or a hook's name, which Kiro only shows: ○ with a note)
label="9. Kiro との連携"
lacks= stale= other= loose=
works_same() {  # $1, $2: the hook or the workflow; the same but for what Kiro only shows
  [ -n "$PY" ] && "$PY" - "$1" "$2" >/dev/null 2>&1 <<'EOF'
import json, sys
def acts(d):  # everything else (trigger, action, command, steps, the workflow's name /chief runs it by) is what it does
    d = {k: v for k, v in d.items() if k != "description"}
    if "hooks" in d:
        d["hooks"] = [{k: v for k, v in h.items() if k not in ("name", "description")} for h in d["hooks"]]
    return d
a, b = (acts(json.load(open(p, encoding="utf-8"))) for p in sys.argv[1:])
sys.exit(a != b)
EOF
}
same() { if [ -d "$1" ]; then [ "$(cd -P "$1" && pwd)" = "$(cd -P "$2" 2>/dev/null && pwd)" ]; else cmp -s "$1" "$2"; fi; }
for x in skills/task:skills/task skills/chief:skills/chief kiro/steering/task-hub.md:steering/task-hub.md; do
  src=$clone/${x%%:*} dst=$KIRO_DIR/${x#*:}
  if [ ! -e "$dst" ]; then lacks="${lacks}$(tilde "$dst")、"
  elif ! same "$dst" "$src"; then other="${other}$(tilde "$dst")、"  # someone's own: the installer keeps it too
  fi
done
for x in kiro/hooks/task-hub-events.json:hooks/task-hub-events.json \
  kiro/workflows/task-hub-events.workflow.json:workflows/task-hub-events.workflow.json; do
  src=$clone/${x%%:*} dst=$KIRO_DIR/${x#*:}
  if [ ! -f "$dst" ] || [ -L "$dst" ]; then lacks="${lacks}$(tilde "$dst")、"
  elif cmp -s "$src" "$dst"; then :
  elif works_same "$src" "$dst"; then loose="${loose}$(tilde "$dst")、"
  else stale="${stale}$(tilde "$dst")、"
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
  [ "$r" = ok ] && [ -n "$other" ] && note "${other%、} は別のものを指しています。インストーラもそのままにします"
  [ "$r" = ok ] && [ -n "$loose" ] && note "${loose%、} は task-hub の今の版と説明(description)か名前だけが違います。動作は同じです"
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
