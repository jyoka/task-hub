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

動かす用の clone を、開発用の clone とは別に作ります。`task` は実行のたびに、リンク先の `bin/task` と
`worker/*.md` を読みます。開発用の clone にリンクすると、そこでブランチを切り替えるたびに、実行中の
タスクボードが使うコードまで変わってしまいます(マージ前のコードで本物のタスクが動く)。

```
git clone https://github.com/jyoka/task-hub.git ~/.local/lib/task-hub
ln -sfn ~/.local/lib/task-hub/bin/task ~/.local/bin/task       # ~/.local/bin must be on PATH
task --version
```

更新は、PR をマージしたあとにこの clone で pull するだけです。`task watch` を動かしているなら、止めてから
起動し直します(実行中のタスクは、始めたときのコードのまま最後まで動きます)。

```
git -C ~/.local/lib/task-hub pull --ff-only
```

task-hub 自体を開発するときは、別の場所に clone して、そこでテストを実行します(`python3 -m unittest discover -s tests -v`)。

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
   ; 作業先リポジトリ = コピーするファイル(複数ならカンマ区切り)
   ; そのまま書くと worktree のルートに同じ名前で、「-> 場所」を付けるとその場所に置きます
   jyoka/aica_ra_a2a_poc = ~/AIprogramming PJ/ai-CA_RA-A2A-PoC/.env, ~/AIprogramming PJ/ai-CA_RA-A2A-PoC/voice-agent/.env -> voice-agent/.env
   ```

   置き場所は worktree の中の相対パスで、外を指すもの(`../`、絶対パス)や、同じ場所を 2 回書いたものは止めます。

   コピーしたファイルはコミットしません。ファイルがない、またはリポジトリで追跡されている名前のときは、開始せずに
   Blocked にします。書いたリポジトリのエージェントは、そのキーで実際に API を呼べる(費用が出る)ことに注意してください。

   たとえば、Kiro しかない仕事用 Mac では `agent = kiro` にして、`kiro-cli whoami` でログイン済みか確認します
   (実行中にエージェントが自分でログインすることはできません)。

## /task と /chief スキルのインストール

同じスキルフォルダがすべてのエージェントで使えます。各エージェントがスキルを探す場所にリンクしてください:

```
for s in task chief; do
  ln -sfn ~/.local/lib/task-hub/skills/$s ~/.claude/skills/$s    # Claude Code
  ln -sfn ~/.local/lib/task-hub/skills/$s ~/.agents/skills/$s    # Codex, Pi
  ln -sfn ../../.agents/skills/$s ~/.kiro/skills/$s              # Kiro
done
```

`/chief` は総指揮のエージェントです。作業している herdr の workspace のペインで、エージェントを起動して `/chief` と
打つと、ボードの状況を伝え、何かが起きるたびに知らせ(`task events --follow` を裏で見張る)、話した作業を
タスクに分けて提案します。登録と開始は、あなたが「うん」と答えたときだけです。マージはしません。
頼んだタスクはその workspace のタブで動き、In review になると自分で閉じます。起きたことを自分から知らせるには、
裏で監視を続けられるエージェント(Claude Code の Monitor など)が要ります。できないエージェントでは、返答のたびに
`task events` で新しい出来事を確かめます。

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
