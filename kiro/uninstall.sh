#!/bin/sh
# kiro/uninstall.sh: removes what kiro/install.sh put on this Mac, and only that: what it recorded under "installed" in
# ~/.local/state/task-hub/install-manifest.json (docs/kiro-ide.md, "インストーラが行うこと").
#   sh kiro/uninstall.sh          lists what it would remove, and removes nothing
#   sh kiro/uninstall.sh --yes    removes it
# Never removed: the board on GitHub (the tasks repository and the Project; it only says how), the GitHub and kiro-cli
# logins, Kiro's settings.json (the installer only turned Workflows on in it), and task-hub's own data (worktrees,
# logs, events). Running it again is safe: what is gone already is skipped.
set -u

BIN_DIR=$HOME/.local/bin
STATE_DIR=$HOME/.local/state/task-hub
MANIFEST=$STATE_DIR/install-manifest.json
ZPROFILE_COMMENT='# task-hub (kiro/install.sh)'
LAUNCHD_LABEL=com.task-hub.watch
MARK='task-hub: made by kiro/install.sh'
# The order things are removed in: launchd first (it runs task watch), then Kiro's files, then what they use;
# uv last, after the Python it installed.
KEYS="launchd kiro-hook kiro-workflow kiro-steering kiro-skill-task kiro-skill-chief kiro-settings config zprofile task
  task-hub kiro-cli kiro-cli-app gh uv-python uv"

yes=
for a in "$@"; do
  case $a in
    --yes) yes=1 ;;
    *) echo "知らない引数です: $a"; echo "次にすること: sh kiro/uninstall.sh で、消すものの一覧を見てください"; exit 1 ;;
  esac
done

tilde() { case $1 in "$HOME"/*) printf '~/%s' "${1#"$HOME"/}" ;; *) printf '%s' "$1" ;; esac; }
get() { plutil -extract "$1" raw -o - "$MANIFEST" 2>/dev/null; }
mine() { case $1 in "$HOME"/?*) true ;; *) false ;; esac; }  # never anything outside the home folder

if [ ! -f "$MANIFEST" ]; then
  echo "kiro/install.sh の記録($(tilde "$MANIFEST"))がありません。このインストーラで入れたものはありません。"
  echo "次にすること: 何もありません(手作業で入れたものは docs/setup.md の手順の逆で消します)"
  exit 0
fi
get version >/dev/null || {
  echo "$(tilde "$MANIFEST") を読めません。何も消していません。"
  echo "次にすること: そのファイルを task-hub の担当者に見せてください"
  exit 1
}

# The board, from config.ini, before it may be removed: for the guide at the end.
config=$HOME/.config/task-hub/config.ini
board() { sed -n "/^\[board\]/,/^\[/s/^$1 *= *\([^ ;#]*\).*/\1/p" "$config" 2>/dev/null | head -n 1; }
project=$(board project) issues=$(board issues)

failed=0 n=0
remove() {  # $1: what it is, the rest: the command that removes it. Only listed without --yes
  what=$1
  shift
  n=$((n + 1))
  if [ -z "$yes" ]; then
    echo "- $what"
  elif "$@" >/dev/null 2>&1; then
    echo "消しました: $what"
  else
    echo "消せませんでした: $what"
    failed=$((failed + 1))
  fi
}
unzprofile() {  # the comment and the line after it that the installer added (with the blank line before), no other
  awk -v c="$ZPROFILE_COMMENT" -v l="$1" '{ line[NR] = $0 }
    END {
      for (i = 1; i <= NR; i++) if (line[i] == c && line[i + 1] == l) { drop[i] = drop[i + 1] = 1; if (line[i - 1] == "") drop[i - 1] = 1 }
      for (i = 1; i <= NR; i++) if (!drop[i]) print line[i]
    }' "$HOME/.zprofile" > "$HOME/.zprofile.tmp" && mv -f "$HOME/.zprofile.tmp" "$HOME/.zprofile"
}
unuv_python() {  # $1: uv, $2: the version. The link uv made in ~/.local/bin goes too
  UV_PYTHON_BIN_DIR=$BIN_DIR "$1" python uninstall "$2" || return
  [ ! -L "$BIN_DIR/python$2" ] || rm -f "$BIN_DIR/python$2"
}
unlaunchd() {  # $1: the plist. Stops task watch first
  domain=gui/$(id -u)
  ! launchctl print "$domain/$LAUNCHD_LABEL" >/dev/null 2>&1 || launchctl bootout "$domain/$LAUNCHD_LABEL" || return
  rm -f "$1" "$STATE_DIR/launchd-stale"
}

if [ -n "$yes" ]; then
  echo "kiro/install.sh が入れたものを消します"
else
  echo "kiro/install.sh が入れたもので、消すもの(まだ何も消していません):"
fi
settings=
for k in $KEYS; do
  v=$(get "installed.$k") && [ -n "$v" ] || continue
  case $k in
    zprofile)
      grep -qxF "$ZPROFILE_COMMENT" "$HOME/.zprofile" 2>/dev/null || continue
      remove "~/.zprofile の task-hub の行($v)" unzprofile "$v"
      ;;
    uv-python)  # a version, in ~/.local/share/uv/python
      uv=$(get installed.uv) || uv=$(command -v uv 2>/dev/null) || uv=
      [ -n "$uv" ] && [ -x "$uv" ] || continue
      remove "uv で入れた Python $v" unuv_python "$uv" "$v"
      ;;
    kiro-settings)  # a file of the user's that the installer changed one setting in: said, not removed
      settings=$v
      ;;
    launchd)
      mine "$v" && [ -f "$v" ] && grep -qF "$MARK" "$v" || continue
      remove "$(tilde "$v")(常駐の task watch を止めてから)" unlaunchd "$v"
      ;;
    task)  # the wrapper, only while it is the installer's
      mine "$v" && [ -f "$v" ] && [ ! -L "$v" ] && grep -q "^# $MARK" "$v" || continue
      remove "$(tilde "$v")" rm -f "$v"
      ;;
    task-hub)
      mine "$v" && [ -d "$v/.git" ] || continue
      remove "$(tilde "$v")(task-hub の clone)" rm -rf "$v"
      ;;
    kiro-cli-app)
      case $v in *.app) mine "$v" && [ -d "$v" ] ;; *) false ;; esac || continue
      remove "$(tilde "$v")" rm -rf "$v"
      ;;
    kiro-cli|kiro-skill-task|kiro-skill-chief|kiro-steering)  # links
      mine "$v" && [ -L "$v" ] || continue
      remove "$(tilde "$v")(リンク)" rm -f "$v"
      ;;
    *)  # files: uv, gh, the copies of the hook and the workflow, config.ini
      mine "$v" && [ -f "$v" ] && [ ! -L "$v" ] || continue
      remove "$(tilde "$v")" rm -f "$v"
      ;;
  esac
done
[ "$n" -gt 0 ] || echo "(もう何も残っていません)"

echo "消さないもの:"
echo "- GitHub のログイン(gh)と kiro-cli のログイン、キーチェーンの task-hub-kiro-api-key(入れていれば)"
echo "- task-hub のデータ: ~/.local/share/task-hub(worktree)、~/.local/state/task-hub(ログ、出来事)"
[ -z "$settings" ] || echo "- $(tilde "$settings") の Workflows の設定(インストーラは有効にしただけです)"
if [ -n "$project$issues" ]; then
  echo "- GitHub のボード(${issues:-?} と Project ${project:-?})。要らなければ、GitHub の画面で消します:"
  [ -n "$issues" ] && echo "    リポジトリ: https://github.com/$issues/settings の一番下「Delete this repository」"
  case $project in
    */*) echo "    Project: https://github.com/users/${project%/*}/projects/${project#*/}/settings の一番下「Delete this project」" ;;
  esac
else
  echo "- GitHub のボード(タスク用のリポジトリと Project)。要らなければ、GitHub の画面の Settings から消します"
fi

if [ -z "$yes" ]; then
  if [ "$n" -gt 0 ]; then
    echo "次にすること: 消してよければ、sh kiro/uninstall.sh --yes を実行してください"
  else
    echo "次にすること: 何もありません"
  fi
  exit 0
fi
if [ "$failed" -gt 0 ]; then  # the manifest stays: run it again
  echo "次にすること: 消せなかったものの権限を確かめて、もう一度 sh kiro/uninstall.sh --yes を実行してください"
  exit 1
fi
rm -f "$MANIFEST" "$STATE_DIR/gh-login.pid" "$STATE_DIR/gh-login.log" "$STATE_DIR/gh-login.command" \
  "$STATE_DIR/kiro-login.command"
echo "次にすること: Kiro を再起動してください(/task と /chief、フック、ワークフローが外れます)"
