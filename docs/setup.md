# セットアップ

ボードはマシン(アカウント)ごとに 1 つです。個人用 Mac は個人の GitHub Project、仕事用 Mac は仕事用の
GitHub Project を使います。手順はどちらも同じです。

## 必要なもの

- Python 3.10 以上(`python3 --version`)と git が入った macOS
- GitHub にログイン済みの `gh` で、Projects の権限があること:

  ```
  gh auth refresh -s project
  gh auth status          # Token scopes に project が含まれていること
  ```

- ログイン済みのエージェント CLI が 1 つ以上: `claude`、`codex`、`pi`、`kiro-cli`。[agents.md](agents.md) を参照してください
- 任意: 起動中の herdr。あると、各実行が herdr サイドバーに専用のワークスペースを持ちます。
  herdr がない場合、実行はバックグラウンドで行われ、`task log <id>` で進行を追います
- 任意: `fzf`。`task start` で矢印キーの選択リストを使うためのものです(ない場合は番号付きメニュー)

## 0.4 から 0.5 に上げるとき

Project にテキスト欄 **Base branch** を追加してください(下の「GitHub 側の準備」の 2)。追加するまで、`task` は
`the Project is missing: text field "Base branch"` と表示して止まります。ターミナルからも追加できます:

```
gh project field-create <Project の番号> --owner <you> --name "Base branch" --data-type TEXT
```

## インストール

```
git clone https://github.com/jyoka/task-hub.git "$HOME/AIprogramming PJ/task-hub"
ln -s "$HOME/AIprogramming PJ/task-hub/bin/task" ~/.local/bin/task       # ~/.local/bin must be on PATH
task --version
```

## GitHub 側の準備(1 回だけ)

1. **タスク用の非公開リポジトリを作ります。** タスクの Issue はすべてここに作られます。

   ```
   gh repo create <you>/tasks --private
   ```

2. **GitHub Project を用意します**(既存のものでも構いません)。Project の設定で次を追加してください。
   - **Status** 欄: GitHub のかんばん(Kanban)テンプレートで作った Project には `Backlog`、`Ready`、`In progress`、
     `In review`、`Done` が最初からあります。そこに **`Blocked`** を 1 つ追加します(大文字小文字は区別しません)。
     任意で **`wait for merge`** も追加できます(レビュー済みでマージ待ちの列。無くても動きます)
   - テキスト欄 **Target repo**、**Agent**、**Base branch** を追加します(Target repo は作業先リポジトリ `owner/name`、
     Agent は使うエージェント名、Base branch は作業を始めるブランチで、Agent と Base branch は空でも構いません。
     `Repo` という名前は GitHub の予約語なので使えません)
   - Board 表示にして、列を Status でグループ化します
   - Workflows は **「Item closed」(Status を Done にする)だけを有効**にします。無効のままのことがあるので必ず確認します。
     ほかの Status を変えるワークフロー(「Item added to project」「Pull request linked to issue」「Pull request merged」)は
     **無効**にします。task-hub が付けた Status を上書きしてしまいます(実際に、PR を出した直後に Backlog に、マージ後に
     In progress に戻されました)。「Auto-close issue」(カードを Done にすると Issue を閉じる)は有効でも構いません

   足りないものがあると、`task` がそれを名前で教えてくれます。

3. **設定ファイル** `~/.config/task-hub/config.ini` を作ります:

   ```ini
   [board]
   project = <you>/2          ; Project の URL の users/<you>/projects/<番号>
   issues = <you>/tasks

   [runner]
   agent = claude             ; このマシンのデフォルトエージェント
   reviewer = agent           ; 任意: 実装後の自動レビュー。agent = タスクと同じエージェント、名前で固定も可
   replanner = agent          ; 任意: エージェントが Blocked で止まったときの仕分け(コメントだけ)
   ```

   `reviewer` を空にするか省略すると、自動レビューは行いません。有効にすると、エージェントの作業後、PR を出す前に
   reviewer が差分を読み、必要なら 1 回だけ実装エージェントに差し戻します。

   テストに API キーなどが要るリポジトリは、`[env]` に書いたファイルを実行のたびに worktree のルートへコピーできます
   (task-hub は自分用の clone で作業するので、手元のチェックアウトの `.env` はそのままでは届きません):

   ```ini
   [env]
   ; 作業先リポジトリ = コピーするファイル(複数ならカンマ区切り)。worktree のルートに同じ名前で置きます
   jyoka/aica_ra_a2a_poc = ~/AIprogramming PJ/aica_ra_a2a_poc/.env
   ```

   コピーしたファイルはコミットしません。ファイルがない、またはリポジトリで追跡されている名前のときは、開始せずに
   Blocked にします。書いたリポジトリのエージェントは、そのキーで実際に API を呼べる(費用が出る)ことに注意してください。

   たとえば、Kiro しかない仕事用 Mac では `agent = kiro` にして、`kiro-cli whoami` でログイン済みか確認します
   (実行中にエージェントが自分でログインすることはできません)。

## /task スキルのインストール

同じスキルフォルダがすべてのエージェントで使えます。各エージェントがスキルを探す場所にリンクしてください:

```
ln -s "$HOME/AIprogramming PJ/task-hub/skills/task" ~/.claude/skills/task    # Claude Code
ln -s "$HOME/AIprogramming PJ/task-hub/skills/task" ~/.agents/skills/task    # Codex, Pi
ln -s ../../.agents/skills/task ~/.kiro/skills/task                          # Kiro
```

## Ready のカードを自動で始める

herdr のペインを 1 つ用意して、次を動かしたままにします:

```
task watch
```

1 分ごとにボードを確認し、Ready のカードを(同時 3 つまで)始めます。外出先でスマホからカードを Ready に
移すだけで、Mac が起きていれば作業が始まります。`task watch` を動かしていないときは、`task` を実行した
タイミングで始まります。

## 初回の実行

まずは使い捨てのリポジトリで試してください:

```
gh repo create <you>/task-sandbox --private --add-readme
task new --title "Add hello.txt" --repo <you>/task-sandbox \
  --goal "Add hello.txt at the repo root containing 'hello'. Acceptance: the file exists."
```

Project に Backlog のカードができます。それを Ready に移すと、`task watch`(または `task`)が拾って
"task 1: Add hello.txt" という herdr ワークスペースで実行します。終わるとカードは In review に移り、Issue に
レポートのコメントが付き、ブランチ `task/1` の PR ができています。PR をマージすると Issue が閉じ、カードは Done になります。
