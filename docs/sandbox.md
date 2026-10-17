# サンドボックス(Linux)

`[sandbox] mode = bwrap` にすると、エージェントは自分のタスクの worktree だけを見て動きます。
あなたの HOME(ほかのリポジトリ、`~/.ssh`、`gh` のログイン、デスクトップ)は見えません。
既定は `off` で、Mac と Windows の動きは変わりません。なぜこの作りかは [design.md](design.md) の決定事項 22 にあります。

## 使う

[bubblewrap](https://github.com/containers/bubblewrap)(`bwrap`)を入れて、`~/.config/task-hub/config.ini` に書きます。

```ini
[sandbox]
mode = bwrap
; エージェントが読めるだけのもの(任意)。カンマ区切り、~ と $変数 が使える
read = ~/.local/share/mise/installs, ~/.cache/ms-playwright
; エージェントが読み書きできるもの(任意)。ツールのキャッシュなど
write = ~/.cache/uv, ~/.npm
```

- `bwrap` がない、Linux でない、user namespace が使えないときは、カードを Blocked にして理由をコメントします。
  エージェントは起動しないので、クレジットは使いません
- ログの先頭に `== sandbox: bwrap` と出ます(`task log <番号>`)
- 包むのはエージェントの起動だけです。実装エージェント、reviewer、replanner のすべてです
- `[setup]` はあなたが書いたコマンドなので、サンドボックスの外で動きます。ただし、2 回目からの実行では、前の実行で
  エージェントが書き換えたかもしれない worktree のファイル(`package.json` の scripts など)の上で動きます

## 中から見えるもの

| 場所 | 見え方 | 理由 |
|---|---|---|
| タスクの worktree | 読み書き | エージェントの仕事場 |
| worktree の `.git`(git ディレクトリの場所を書いたファイル) | 読むだけ | 下の「git の設定から外に出させない」 |
| clone の `.git`(オブジェクト、ref、worktree の git ディレクトリ `.git/worktrees/<名前>`) | 読むだけ | ほかのブランチを書き換えさせない。`git status` と `git diff` は読むだけで動く |
| `/usr`、`/etc`、`/opt`、`/nix`、`/sys` | 読むだけ | コンパイラ、Python、証明書、DNS の設定 |
| `PATH` の中のフォルダと、エージェントのプログラムのあるフォルダ | 読むだけ | `claude`、`node` などを見つけるため。リンクは元の場所も見せる |
| エージェント CLI 自身のファイル(`[sandbox] agent_files`) | 読み書き | ログイン、設定、記録。task-hub は記録から使用量を読む |
| その中の、コードを動かす設定(下の一覧) | 読むだけ | 中から hook や MCP サーバーを書き残させない |
| `[sandbox] read`、`[sandbox] write` | 読むだけ、読み書き | あなたが足すもの |
| HOME、`/tmp`、`/run` | 空(実行ごとに消える) | ほかのファイルを見せない |
| ネットワーク | 使える | エージェントの API、パッケージ、Web の調べもの |

`agent_files` の既定は `~/.claude, ~/.claude.json, $CLAUDE_CONFIG_DIR, ~/.codex, ~/.pi, ~/.kiro, ~/.local/share/kiro-cli` です。
あるものだけを見せます。変えたいときは `[sandbox] agent_files = ...` で全体を書き直します。

そのうち、次に CLI を起動したときにコードを動かしたり指示を変えたりするものは、読むだけにします。中のエージェントが
ここに hook や MCP サーバーを書き残すと、あなたが次にサンドボックスなしで CLI を起動したときに、外であなたの権限で
動いてしまうからです。一覧は `bin/task` の `SANDBOX_AGENT_CODE` です。

- Claude Code: `~/.claude.json`、`~/.claude/` の `settings.json`、`CLAUDE.md`、`hooks/`、`commands/`、`agents/`、
  `skills/`、`plugins/`、`output-styles/`(`$CLAUDE_CONFIG_DIR` の下の同じもの)
- Codex: `~/.codex/` の `config.toml`、`AGENTS.md`、`prompts/`、`skills/`
- Pi: `~/.pi/agent/` の `settings.json`、`AGENTS.md`、`extensions/`、`prompts/`、`skills/`
- Kiro: `~/.kiro/` の `settings/`、`agents/`、`hooks/`、`steering/`、`prompts/`

読み書きのフォルダの中にあるのに、まだないものは、開始のときに空で作ります(フォルダ、空のファイル、JSON は `{}`)。
ないままだと、エージェントが新しく作れてしまうからです。どれかがリンク(dotfiles の管理など)だと、開始の前に
カードを Blocked にします。`bwrap` はリンクの上に重ねられず、エージェントがリンクを消して別のファイルに
差し替えられるためです。ふつうのファイルにするか、`agent_files` から外してください。

サンドボックスの中では、プラグインの更新や `claude mcp add` のように、これらを書く操作は失敗します。

環境変数のうち、`GH_TOKEN`、`GITHUB_TOKEN`、`SSH_AUTH_SOCK`、`DBUS_SESSION_BUS_ADDRESS`、`WAYLAND_DISPLAY`、
`DISPLAY`、`XDG_RUNTIME_DIR`、`TMPDIR` などは消します。API キーなど、ほかの変数はそのまま渡ります。

## commit、push、PR はどうなるか

変わりません。エージェントはファイルを編集するだけで、commit、push、PR は task-hub がサンドボックスの外で行います
([design.md](design.md) の決定事項 3)。エージェントには `gh` のログインも SSH の鍵も渡しません。git のメタデータは
読むだけなので、中のエージェントは `git add` や `git commit` ができません(しなくてよいものです)。

### git の設定から外に出させない

task-hub は、エージェントが書いた worktree で外から git を動かします(`git add -A`、`git commit`、`git push` など)。
git は worktree の `.git` が指す git ディレクトリの設定を読み、`core.fsmonitor` や hook はコマンドとして動きます。
中のエージェントが `.git` や `commondir` を自分の作った git ディレクトリに向けると、その設定のコマンドが外であなたの
権限で動いてしまいます。そこで次の 2 つで防ぎます。

- 中では git のメタデータを全部読むだけにします。worktree の `.git` は worktree の上に読むだけで重ね、
  `.git/worktrees/<名前>`(`commondir`、`gitdir`、`config.worktree`、index)は clone の `.git` ごと読むだけです
- 外の git(`bin/task` の `git_wt`)は `-c core.fsmonitor= -c core.hooksPath=/dev/null` で動かし、毎回その前に
  `.git` と `commondir` が task-hub の clone を指したままかを確かめます(`check_git_links`)。指していなければ git を
  動かさず、カードを Blocked にします
- 同じ確認で、worktree の中にほかの `.git`(入れ子のリポジトリ、サブモジュール)があれば、外の git を動かさず、カードを
  Blocked にします。外の git は入れ子のリポジトリの設定も読み、`add`、`status`、`diff` のたびに `filter.<名前>.clean` や
  `diff.<名前>.textconv` のコマンドを動かすからです。コマンドを動かす設定は多く、`-c` で全部は切れません。
  そのため、サブモジュールのあるリポジトリはサンドボックスでは動かせません(開始のときに Blocked になります)

`mode = off` のときは、どちらもしません(エージェントがもともと外で動くので、守る意味がありません)。task-hub の
commit でリポジトリの hook が動かないのは、サンドボックスがオンのときだけです。

## 確かめ方

テスト `test_sandboxed_agent_sees_only_its_worktree_yet_the_run_opens_a_pr`(`tests/test_task.py`)が、偽物の
エージェントを `bwrap` の中で動かし、次を確かめます。`bwrap` が動かない環境では skip します。

- worktree の `README.md` は読める
- HOME の別のファイルと `config.ini` は読めない
- `GH_TOKEN` は渡らない
- Goal の Rules の設定ファイルは書き換えられない
- `~/.claude/settings.json`、`~/.claude.json`、`~/.claude/hooks/` には書けない。`~/.claude/projects` には書ける
- worktree の `.git`、git ディレクトリの `commondir` と `config.worktree` は書き換えられず、`.git` を差し替えられない。
  エージェントが用意した `core.fsmonitor` と hook は、外の git で動かない
- それでも task-hub が push して PR を作る

テスト `test_sandboxed_host_git_runs_no_command_the_agent_set_up` は、外の git(`git_wt`)だけを確かめます。worktree の中の
入れ子のリポジトリの `core.fsmonitor` は `git diff` で動かず、`.git` を別の git ディレクトリに向けると git を動かさずに止まります。

本物の Claude Code では、2026-10-17 に次を手で確かめました(Claude Code 2.1.302、bubblewrap 0.12.0、Arch 系の Linux)。

- `claude -p --dangerously-skip-permissions` がサンドボックスの中で答えを返す
- 記録が `~/.claude/projects` に残り、task-hub が使用量を読める
- `~/.ssh`、`~/.config/gh`、`~/.config/task-hub` は見えない。clone の `.git` には書けない
- `.claude/settings.local.json` の deny が `--dangerously-skip-permissions` でも効く
- `~/.claude.json` と `~/.claude/settings.json` を読むだけにしても答えを返し、記録も残る。中から
  `~/.claude/settings.json` に書こうとすると read-only で失敗し、ホストのファイルは変わらない

Codex、Pi、Kiro はサンドボックスの中で動かしていません(未確認)。

## タスクごとの決まり(Rules)

Goal に `Rules` の見出しを書くと、`can:` / `ask:` / `never:` の行が Claude Code の権限の設定になります。
書き方は [task-format.md](task-format.md#rules-タスクごとの決まり) にあります。サンドボックスが on のときは、
その設定ファイルをエージェントが書き換えられないようにします。off でも Rules は効きますが、エージェントが
ファイルを書き換えると、同じ実行の reviewer や差し戻しの起動に効かなくなることがあります。

## ブラウザ(Web のタスク)

ヘッドレスのブラウザは、Playwright の MCP サーバーでエージェントに渡せます。Claude Code なら、1 回だけ登録します。

```sh
claude mcp add --scope user playwright -- npx @playwright/mcp@latest --headless --isolated
npx playwright install chromium        # ブラウザを ~/.cache/ms-playwright に入れる
```

サンドボックスの中から使うには、`[sandbox]` に足します。

```ini
read = ~/.cache/ms-playwright
write = ~/.npm
```

- 登録は `~/.claude.json` に入るので、`agent_files` で中に届きます。中では読むだけなので、登録はサンドボックスの外で行います
- `--isolated` は、ブラウザのプロファイルを毎回まっさらにします。あなたのブラウザのログインは使いません
- ネットワークはつながっているので、どのサイトでも開けます。サイトを絞るなら Goal の Rules で `never: mcp__playwright__*` などを書きます

この手順は、2026-10-17 の時点でサンドボックスの中では確かめていません。

## 制限

- Linux だけです。Mac と Windows では `mode = off` のままにします
- `[setup]` は外で動き、前の実行でエージェントが書き換えたかもしれないファイルを使います(`npm install` が
  `package.json` の scripts を動かすなど)。これは守れません。気になるなら `[setup]` を使わないか、中身を確かめます
- サブモジュールのあるリポジトリと、`.git` を中に持つフォルダ(git から入れた `node_modules` の依存など、`[setup]`
  が作ったものも含みます)のある worktree は動かせません。上のとおり、外の git を動かす前に Blocked にします
- 入れ子の `.git` の確認は、外の git を動かすたびに worktree 全体をたどります。ファイルがとても多い worktree では、
  その分だけ遅くなります
- ネットワークは絞りません。エージェントは worktree の中のもの(`[env]` でコピーした `.env` を含む)を外に送れます
- `agent_files` は読み書きできるので、エージェントは同じ CLI のほかのプロジェクトの記録も読めます
- HOME は毎回空なので、`~/.cache` などのキャッシュは残りません。遅いときは `write` に足します
- mise のシムのように、HOME の中の設定を書き換えるツールは動かないことがあります。`PATH` で先に本物のプログラムが
  見つかるようにするか、`read` に足します
