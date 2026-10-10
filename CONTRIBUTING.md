# 貢献のしかた

バグ報告、機能の要望、PR を歓迎します。

## Issue と Discussions の使い分け

| 送りたいもの | 送り先 |
|---|---|
| バグ報告 | `task feedback` で開くフォーム(版と OS が入った状態で開く)。または [新しい Issue](https://github.com/jyoka/task-hub/issues/new/choose) の「バグ報告」 |
| 機能の要望 | `task feedback --feature`。または新しい Issue の「機能の要望」 |
| 使い方の質問、設定の相談、まだ形になっていないアイデア | [Discussions](https://github.com/jyoka/task-hub/discussions) |
| 脆弱性 | 公開の Issue には書かない。[SECURITY.md](SECURITY.md) の手順で非公開に |

Issue は「直す」「作る」ものだけに絞っています。空の Issue は作れません。

あなたのボードのカードは、config の `[board] issues` に書いた別のリポジトリにできます。このリポジトリの Issue とは
混ざりません。

## PR を出す流れ

1. このリポジトリを fork し、開発用の clone を作る。`task` を動かしている clone(`~/.local/lib/task-hub`)とは
   分けます。同じ clone でブランチを切り替えると、動いているボードのコードまで変わるためです
   ([docs/setup.md](docs/setup.md#インストール))
2. `main` からブランチを切る。名前は `fix/...`、`feat/...`、`docs/...` のように、何の変更かが分かるものにします
3. 変更し、テストを足し、下の「テスト」を通す
4. push して、`main` に向けた PR を出す。本文には次を書きます
   - 何を、なぜ変えたか(関係する Issue があれば `Closes #番号`)
   - どう確かめたか(動かしたコマンドと結果)
   - 確かめていないこと(Windows の実機、本物の GitHub Project など)

1 つの PR は、1 つの関心ごとにします。10〜15 分でレビューできる大きさが目安です。機能、バグ、ドキュメントの
ように性質の違う変更は、PR を分けます。

コミットメッセージは、何をしたかを 1 行目に日本語で書きます(`git log` を参考にしてください)。

PR で送った変更は、このリポジトリと同じ [MIT ライセンス](LICENSE) で公開されます。

## リポジトリの中身

```
AGENTS.md              エージェント向けの入口(CLAUDE.md はこれを読み込むだけ)
LICENSE                MIT ライセンス
bin/task               CLI(Python 3 の標準ライブラリだけ。git、gh、動いていれば herdr を使う)
worker/PROMPT.md       worker の指示書(実行のたびに渡す)
worker/REVIEW.md       reviewer の指示書(受け入れ条件を 1 つずつ、根拠付きで)
worker/REPLAN.md       replanner の指示書(answered / human / goal-conflict、根拠付き)
skills/task/SKILL.md   /task スキル
skills/chief/SKILL.md  /chief スキル
pi/task-events.ts      Pi の拡張機能: 出来事で /chief を起こす(Pi にはバックグラウンド実行がないため)
claude/task-board/     Claude Code の mod: ボードをステータスラインとペインに出す(task list と手元の events.jsonl・metrics.jsonl を読むだけで、LLM は使わない)
kiro/                  Kiro IDE 用の部品と、かんたんセットアップ(install.sh、doctor.sh、uninstall.sh)
kiro/board-extension/  Kiro IDE の拡張: ボードをサイドバーとステータスバーに出す。船の絵と実績バッジつき(task list と手元の events.jsonl・metrics.jsonl を読むだけで、LLM は使わない)
slack-triage/          Slackトリアージ: スレッドをコピーして ⌃⌥S でタスクを提案する(docs/slack-triage.md)
.kiro/steering/        このリポジトリを Kiro で開いたときの約束(「セットアップして」でインストーラを動かす)
windows/               Windows 用のインストーラ(install.ps1)と、task watch を常駐させるスクリプト(task-watch.ps1)
tests/test_task.py     テスト: python3 tests/run.py(並べて動かす。1 件ずつなら python3 -m unittest discover -s tests -v)
tests/test_windows.py  Windows だけで動くテスト(GitHub Actions の windows-latest で実行)
.github/ISSUE_TEMPLATE/  Issue のフォーム(バグ報告、機能の要望)。task feedback が開く
docs/                  セットアップ、エージェント、設計、形式、運用、リリース、教訓
```

`task` は、開発用とは別の clone(`~/.local/lib/task-hub`)から動かします。新しい版が出ると `task list` と
`task watch` が 1 行で知らせるので、`task update` で更新します(clone を最新のリリースまで進め、launchd の
`task watch` の再起動と Kiro IDE の定義のコピーし直しもまとめて行います。[docs/setup.md](docs/setup.md#インストール))。

## テスト

`bin/task` は Python 3.10 以上の標準ライブラリだけで書いています。テストも同じで、インストールは要りません。

```
python3 tests/run.py
```

テストを 1 件ずつ別のプロセスで、CPU の数だけ並べて動かします(10 コアで約 3.5 分)。並べる数は `-j 4` のように
指定できます。名前を渡すと、その文字を含むテストだけを動かします(例: `python3 tests/run.py test_task`)。
1 件ずつ順に動かすときは `python3 -m unittest discover -s tests -v` です(全体で 13 分ほど)。
作業中は、変えた部分のテストだけを動かすと速く済みます。

```
python3 -m unittest tests.test_task.TaskTest -k feedback -v
python3 -m unittest tests.test_task.TaskTest.test_version -v
```

| テスト | 中身 |
|---|---|
| `tests/test_task.py` | `bin/task` をサブプロセスとして動かす。GitHub(`gh`)、エージェント、herdr はフェイクに置き換え、git は本物を使う |
| `tests/test_install.py` | Kiro 用のインストーラ(`kiro/install.sh` など) |
| `tests/test_windows.py` | Windows だけで動く(ほかでは skip)。GitHub Actions の `windows-latest` で、push のたびに動く |
| `kiro/board-extension` の `npm test` | Kiro IDE の拡張。Node.js 22.18 以上か 23.6 以上([docs/kiro-ide.md](docs/kiro-ide.md)) |

- バグを直すときは、まず使う人から見た動きで再現するテストを書き、失敗するのを見てから直します
- テストは GitHub やエージェントの本物を呼びません。外部とのやりとりは、`tests/test_task.py` の先頭にあるフェイクに
  足します
- フェイクは本物より寛容です。GitHub やエージェントとのやりとりを変えたときは、本物で一度動かして確かめ、PR の本文に
  そう書きます([docs/lessons.md](docs/lessons.md))
- Windows で動きが変わる部分(プロセス、パス、シェル)は、`bin/task` の `WINDOWS` で分けます
  ([docs/windows.md](docs/windows.md))

## README と docs の書き方

README と `docs/` は日本語で書きます。読むのは、task-hub を使う人と、このリポジトリで作業するエージェントです。

- 結論を先に書きます。前置きは書きません
- 1 文は短くします(目安は 40 字)。1 文に要点を詰め込みません
- 同じものには、毎回同じ語を使います(カード、タスク、Issue、worktree など)。途中で言い換えません
- 3 つ以上の並び、手順、比較は、箇条書きか表にします
- ハイフンは半角の `-` を使います。em ダッシュや en ダッシュは使いません
- コマンド、ファイル名、設定のキーは `` ` `` で囲みます
- 確かめていないことは、確かめていないと書きます。いつ、何で確かめたかを添えます(例: 「2026-10-01 の試験では未確認」)
- 使い方が変わる変更は、同じ PR で README と関係する docs も直します。コマンドを足したら、README の「コマンド」の表と
  `task help` の両方に出します

### README の構成

README は、初めて来た人が最初の画面で「何か」「なぜ使うか」「どう始めるか」をつかむためのページです。
詳しいことは docs に置き、README からリンクします。150 行前後に収めます。

| 順 | 見出し | 中身 |
|---|---|---|
| 1 | `# task-hub` | 太字の一言の説明、CI のバッジ、人が決める 2 つのこと、Kiro IDE の人への案内 |
| 2 | `## しくみ` | 6 段階くらいの Mermaid の図 1 枚と、箇条書き 3 つ |
| 3 | `## 特長` | 1 行ずつ、7 つまで |
| 4 | `## はじめる` | 必要なもの、コマンド 3 つ前後、最小の設定。詳しくは setup.md へ |
| 5 | `## 使い方` | 3 通りの使い方の表と、頼んでからマージまでの例 1 つ。詳しくは usage.md へ |
| 6 | `## タスクの一生` | 列ごとの表(何が起きているか、あなたの対応) |
| 7 | `## コマンド` | 公開しているコマンドすべてを 1 行ずつ。フラグの全部は `task help` に任せる |
| 8 | `## ドキュメント` | はじめる・使う・仕組み・開発する の 4 列の表(ほかの docs がこの見出しにリンクしている) |
| 9 | `## バグ報告と要望` | `task feedback`、Discussions、SECURITY.md |
| 10 | `## ライセンス` | [LICENSE](LICENSE) へのリンク 1 行 |

- 版の番号や変更の履歴は README に書きません。リリースノートに書きます([docs/release.md](docs/release.md))
- コマンドを足したら、README の「コマンド」の表に 1 行足します。表に全部のコマンドがあることはテストが確かめます
- 新しい見出しを足したくなったら、まず docs のどこかに置けないかを考えます

置き場所の目安です。

| 内容 | 場所 |
|---|---|
| 何ができるか、使い方の全体、コマンドの一覧 | [README.md](README.md) |
| タスクの頼み方、設定、役割、手元に残るもの | [docs/usage.md](docs/usage.md) |
| セットアップ、エージェント、運用、形式 | `docs/` の各ページ([README の「ドキュメント」](README.md#ドキュメント)) |
| なぜこの作りなのか | [docs/design.md](docs/design.md) |
| 作って試して分かったこと | [docs/lessons.md](docs/lessons.md) |

`bin/task` のコード、コメント、コマンドの出力は英語です。周りのコードの書き方に合わせてください。
