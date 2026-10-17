# サンドボックス(Linux)

`[sandbox] mode = user` にすると、エージェントを専用の Linux ユーザー(既定は `task-agent`)で動かします。
あなたの HOME(ほかのリポジトリ、`~/.ssh`、`gh` のログイン、task-hub の設定、デスクトップ)は、Unix の権限で
そのユーザーから届きません。既定は `off` で、Mac と Windows の動きは変わりません。なぜこの作りかは
[design.md](design.md) の決定事項 22 にあります。

## 用意する(マシンごとに 1 回、sudo で)

専用ユーザー、共有のフォルダ、sudo の設定は、task-hub ではなく
[workenv_setting](https://github.com/jyoka/workenv_setting) の `scripts/setup_agent_user.sh install` が作ります
(root が要るので、無人の実行ではできません)。作るのは次のものです。

| もの | 中身 |
|---|---|
| ユーザー | `task-agent`(グループ `task-agent`、`task-agents`)、HOME は `/var/lib/task-agent` |
| 共有のフォルダ | `~/.local/share/task-hub/repos` と `~/.local/share/task-hub/worktrees`。グループ `task-agents`、setgid、あなたと `task-agent` に読み書きの ACL(既定の ACL も)。その上の `~`、`~/.local`、`~/.local/share`、`~/.local/share/task-hub` には、`task-agent` に通るだけ(`x`)の ACL |
| sudo | `/etc/sudoers.d/task-agent`: あなたから `task-agent` へ、パスワードなし(`NOPASSWD`、`CWD=*`)。root にはなれない |
| git | `task-agent` の git の名前とメール、`safe.directory`(共有のフォルダ)、`gh` を資格ヘルパーに |
| GitHub | `task-agent` の `gh auth login`。トークンはタスクのリポジトリの contents と pull requests だけの fine-grained にします |

そのあと、`task-agent` でエージェント CLI にログインします(Claude Code なら `sudo -u task-agent -H claude`、
`/login`)。エージェント CLI が `task-agent` の `PATH`(`/usr/local/bin:/usr/bin` など。sudo の `secure_path`)に
あることも確かめます。あなたの HOME の下に入れたもの(mise など)は、`task-agent` からは見えません。

そして `~/.config/task-hub/config.ini` に書きます。

```ini
[sandbox]
mode = user
user = task-agent     ; 省略するとこれ
```

- ユーザーがいない、Linux でない、`sudo -n -u task-agent` が通らない、共有のフォルダに書けないときは、カードを
  Blocked にして理由をコメントします。エージェントは起動しないので、クレジットは使いません
- ログの先頭に `== sandbox: user task-agent` と出ます(`task log <番号>`)
- sudo は環境変数を消します。エージェントに渡したい変数(API キーなど)は `[runner] pass_env` に書くと、
  `sudo --preserve-env` で渡ります。`GH_TOKEN` や `SSH_AUTH_SOCK` は書かなければ渡りません

## 専用ユーザーで動くもの

task-hub は、共有のフォルダ(clone と worktree)の上では、自分のユーザーで何も動かしません。エージェントは
そこの git の設定も hook も書けるので、あなたのユーザーで git を動かすと、エージェントの仕込んだコマンドが
あなたの権限で動くからです(決定事項 22)。

| もの | 誰が | どうやって(`bin/task`) |
|---|---|---|
| エージェント(実装、reviewer、replanner、差し戻し) | `task-agent` | `as_agent`: `sudo -n -u task-agent -H -D <worktree> --` |
| `[check]`、`[setup]` | `task-agent` | 同じ。`[check]` は `task-agent` のログインを確かめる |
| clone、fetch、worktree、`git add`、`commit`、`diff`、`restore` | `task-agent` | `git_shared` |
| push | `task-agent`(そのユーザーの `gh` のログイン) | `finish` |
| worktree のファイルの読み書き(レポート、Rules、`[env]` のコピー、`.git/info/exclude`) | `task-agent` | `shared_read`、`shared_write`、`shared_unlink` |
| PR を開く、Issue にコメント、カードを動かす | あなた | `gh`(GitHub の API だけ。git は動かさない) |
| push した結果(先に進んでいるか、PR の大きさ) | あなた | `branch_compare`: `gh api repos/<repo>/compare/<base>...<branch>` |

エージェントが worktree に置いたリンク(`.task-report.md` を `~/.ssh/id_ed25519` に向けるなど)も、`task-agent` で
読むので、`task-agent` が読めるものにしか届きません。task-hub 自身のプロセス(herdr のペインのシェル、
`task _run`)は、worktree ではなく `~/.local/share/task-hub` で動きます。git を見るシェルのプロンプト(starship など)が、
worktree の中であなたの権限で git を動かさないようにするためです。

## 確かめ方

テスト `test_agent_run_as_the_sandbox_user_sees_only_its_worktree_yet_the_run_opens_a_pr`(`tests/test_task.py`)が、
偽物のエージェントを本物の `task-agent` で動かします。`sudo -n -u task-agent` が通らないマシンでは skip します
(ユーザーは `TASK_TEST_SANDBOX_USER` で変えられます)。テストのフォルダに、上の用意と同じ ACL を付けて確かめるのは次です。

- worktree の `README.md` は読める
- あなたのファイル(0600 の `secret.txt`、0700 のフォルダの中の `config.ini`)は読めない
- `GH_TOKEN` は渡らない。エージェントは `task-agent` として動く
- エージェントが clone に置いた pre-commit の hook と `core.fsmonitor` は、task-hub の commit で動くが、動いたのは
  毎回 `task-agent` で、あなたのユーザーでは 1 度も動かない
- それでも commit と push ができ、PR ができる。PR の大きさは GitHub の比較(偽物の `gh`)から読む

本物のマシンでは、2026-10-17 に `task-agent` で次を手で確かめました(sudo 1.9.17p2、Arch 系の Linux)。

```sh
sudo -n -u task-agent -H -D ~/.local/share/task-hub/worktrees/5 -- sh -c '
  cat ~joka/.ssh/* ~joka/.config/gh/hosts.yml ~joka/.config/task-hub/config.ini ~joka/.claude.json  # すべて Permission denied
  head -1 README.md                                  # 読める
  git push --dry-run origin HEAD:task/5               # Everything up-to-date(task-agent の gh で)
  gh api user -q .login'
```

本物の Claude Code を `task-agent` で動かすのは、まだ確かめていません。`task-agent` に Claude Code が入っておらず、
ログインもしていないためです(2026-10-17)。

## タスクごとの決まり(Rules)

Goal に `Rules` の見出しを書くと、`can:` / `ask:` / `never:` の行が Claude Code の権限の設定になります。
書き方は [task-format.md](task-format.md#rules-タスクごとの決まり) にあります。サンドボックスとは別の仕組みで、
off でも効きます。ただし、ファイルは worktree の中にあるので、エージェントは書き換えられます。書き換えは
次の起動(同じ実行の reviewer、差し戻し、次の実行)から効き、開始のたびに task-hub が書き直します。

## ブラウザ(Web のタスク)

ヘッドレスのブラウザは、Playwright の MCP サーバーでエージェントに渡せます。登録もブラウザも `task-agent` の
HOME に入れます。

```sh
sudo -u task-agent -H claude mcp add --scope user playwright -- npx @playwright/mcp@latest --headless --isolated
sudo -u task-agent -H npx playwright install chromium     # /var/lib/task-agent/.cache/ms-playwright に入る
```

- `task-agent` には `npx`(Node.js)が要ります。`/usr/bin` に入れるか、`task-agent` の HOME に入れます
- `--isolated` は、ブラウザのプロファイルを毎回まっさらにします。あなたのブラウザのログインは使いません
  (`task-agent` からはもともと届きません)
- ネットワークは絞りません。サイトを絞るなら Goal の Rules で `never: mcp__playwright__*` などを書きます

この手順は、2026-10-17 の時点で確かめていません(`task-agent` に Claude Code がまだないため)。

## 制限

- Linux だけです。Mac と Windows では `mode = off` のままにします
- **GitHub のトークンの範囲がそのまま守りの範囲です。** `task-agent` はそのトークンで、許されたリポジトリの
  どのブランチにも push できます。fine-grained のトークンで、タスクのリポジトリの contents と pull requests
  だけにします。`main` は GitHub のブランチ保護で守ります。classic のトークン(`ghp_`)は、アカウントの
  すべてのリポジトリに届き、`delete_repo` などの scope もありうるので使いません。`sudo -u task-agent -H gh auth status`
  で確かめられます
- エージェントは、共有のフォルダにあるほかのタスクの worktree と clone も読み書きできます(`[env]` でコピーした
  `.env` も)。同じマシンで同時に動く別のタスクから守るものではありません
- ネットワークは絞りません。エージェントは worktree の中のもの(`.env` を含む)を外に送れます
- エージェントの使用量(`task stats` のトークン)は読めません。記録が `task-agent` の HOME
  (`/var/lib/task-agent/.claude/projects`)にあり、あなたからは読めないからです
- worktree を **あなたのユーザーで** 開く(`task open`、エディタ、git を見るシェルのプロンプトで `cd` する)と、
  エディタやプロンプトの git があなたの権限で動き、エージェントの仕込んだ設定(`core.fsmonitor` など)を動かします。
  中を見るときは `sudo -u task-agent -H git -C <worktree> diff` のように、`task-agent` で見るか、PR で見ます
- **`user` から `off` に戻すときは、先に `sudo scripts/setup_agent_user.sh uninstall`(workenv_setting)で
  セットアップを戻し、`sudo pkill -u task-agent` でエージェントが裏に残したプロセス(`nohup … &` など)を止めてから、
  `~/.local/share/task-hub/repos` と `worktrees` をフォルダごと消します**(中の作業は先に push するか保存します)。
  `off` では task-hub があなたのユーザーで clone と worktree に git を動かすので、エージェントが仕込んだ
  `core.fsmonitor` や hook があなたの権限で動くからです。uninstall は ACL を外して持ち主をあなたに戻すだけで、
  仕込まれた設定や hook は clone に残ります。中を空にするだけでは、ACL が残っていれば次の clone もまた
  `task-agent` が書けます。そこで `off` の task-hub は、次のどちらかの間、開始を Blocked にし、後片付けもせずに残し、
  メッセージで上の手順を促します。
  - `repos` か `worktrees` に `task-agent` か `task-agents` の ACL(access か default)が一つでもある
    (`getfacl` で見えるもの。空かどうかでは決めません)
  - `user` が動いたあと(印は `~/.local/share/task-hub/sandbox-used`)、`repos` か `worktrees` に何か残っている。
    印は、`user` で動いたときと、`off` で ACL を見つけたとき(印ができる前に `user` を使ったマシン)に作られ、
    ACL がなく両方が空か無くなったときに消えます
- `off` から `user` に変えたときにすでにある clone と worktree は、共有のフォルダの ACL が付いていれば
  そのまま使えます。付いていなければ、セットアップのスクリプトをもう一度動かします
