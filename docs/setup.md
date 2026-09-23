# セットアップ

ボードはマシンごとに 1 つです。仕事のタスクは仕事用 Mac に、個人のタスクは個人用 Mac に置いたままになります。
セットアップ手順はどちらも同じです。

## 必要なもの

- Python 3.10 以上(`python3 --version`)と git が入った macOS
- GitHub にログイン済みの `gh`: `gh auth status`。task-hub はリポジトリの clone、PR の作成、
  PR がマージされたかの確認にこれを使います
- ログイン済みのエージェント CLI が 1 つ以上: `claude`、`codex`、`pi`、`kiro-cli`。[agents.md](agents.md) を参照してください
- 任意: 起動中の herdr。あると、各実行が herdr サイドバーに専用のワークスペースを持ちます。
  herdr がない場合、実行はバックグラウンドで行われ、`task log <id>` で進行を追います
- 任意: `fzf`。`task start` で矢印キーの選択リストを使うためのものです(ない場合は番号付きメニュー)

## インストール

```
git clone https://github.com/jyoka/task-hub.git "$HOME/AIprogramming PJ/task-hub"
ln -s "$HOME/AIprogramming PJ/task-hub/bin/task" ~/.local/bin/task       # ~/.local/bin must be on PATH
task --version
```

ボード(あなたのタスク)は初回利用時に、このリポジトリの外の `~/.local/share/task-hub/board` に作成されます。
そのため、マシンごとに専用の非公開ボードを持つことになります。別の場所に置きたい場合は `TASK_HUB_DIR` を設定してください。

## /task スキルのインストール

同じスキルフォルダがすべてのエージェントで使えます。各エージェントがスキルを探す場所にリンクしてください:

```
ln -s "$HOME/AIprogramming PJ/task-hub/skills/task" ~/.claude/skills/task    # Claude Code
ln -s "$HOME/AIprogramming PJ/task-hub/skills/task" ~/.agents/skills/task    # Codex, Pi
ln -s ../../.agents/skills/task ~/.kiro/skills/task                          # Kiro
```

## このマシンのデフォルトエージェントを選ぶ

`~/.config/task-hub/config.ini` を作成します(任意です。ない場合のデフォルトエージェントは `claude` です):

```ini
[runner]
agent = kiro
```

たとえば、Kiro しかない仕事用 Mac では次のようにします:

```
mkdir -p ~/.config/task-hub
printf '[runner]\nagent = kiro\n' > ~/.config/task-hub/config.ini
kiro-cli whoami          # must be logged in; runs cannot log in by themselves
```

エージェントのコマンドを変更したり、別のエージェントを追加したりする方法は [agents.md](agents.md) にあります。

## 初回の実行

まずは使い捨てのリポジトリで試してください:

```
gh repo create <you>/task-sandbox --private --add-readme
task new --title "Add hello.txt" --repo <you>/task-sandbox \
  --goal "Add hello.txt at the repo root containing 'hello'. Acceptance: the file exists."
task start
```

"task 1: Add hello.txt" という名前の herdr ワークスペースが現れ、その中でエージェントが作業します。終わったら
`task` を実行してください。タスクは `review` になっているはずで、ブランチ `task/1` の PR があり、その説明文には
Report と Please review が含まれています。それをマージしてもう一度 `task` を実行すると、タスクは `done` になります。
