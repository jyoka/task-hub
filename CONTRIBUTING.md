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
3. 変更し、テストを足す。手元では関係する短いテストを通し、全部は PR の GitHub Actions で通す
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
bin/task               CLI の入口(task_hub.py を読み込むだけのランチャー。版の VERSION もここ)
bin/task_hub.py        CLI の本体(Python 3 の標準ライブラリだけ。git、gh、動いていれば herdr を使う)
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
durable/               実験: B の実行役(Pi Durable、Node)。[agents] durable で動くエージェントの 1 つ(durable/README.md)
rust/                  実験: task-rs(Rust の読むだけの一覧と TUI)。task には組み込まない。配布は task-rs-v* の pre-release(rust/README.md)
assets/brand/          伝え方の見た目: 色と字の CSS の変数(tokens.css)とバナー(docs/brand.md)
assets/media/          README と LP の画像と動く画像。tests/media.py が撮る(docs/media.md)
site/                  LP(1 ページ)。https://jyoka.github.io/task-hub/ に .github/workflows/pages.yml が出す。手元では python3 -m http.server で開く(site/README.md)
windows/               Windows 用のインストーラ(install.ps1)と、task watch を常駐させるスクリプト(task-watch.ps1)
tests/test_task.py     テスト: 全部は GitHub Actions。手元では python3 tests/run.py <名前の一部>
tests/test_windows.py  Windows だけで動くテスト(GitHub Actions の windows-latest で実行)
tests/bench.py         弱い PC 向けの計測(テストではない。頼まれたときとリリースの前に動かす。docs/benchmark.md)
tests/durable_bench.py 止まった実行の再開の A・B・C を本物のモデルで比べる実験(テストではない。頼まれたときだけ。docs/durable-runs-comparison.md)
tests/media.py         README と LP の画像を、架空のカードを動かして撮る(テストではない。画面が変わったときに動かす。docs/media.md)
.github/ISSUE_TEMPLATE/  Issue のフォーム(バグ報告、機能の要望)。task feedback が開く
docs/                  セットアップ、エージェント、設計、形式、運用、リリース、教訓
```

`task` は、開発用とは別の clone(`~/.local/lib/task-hub`)から動かします。新しい版が出ると `task list` と
`task watch` が 1 行で知らせるので、`task update` で更新します(clone を最新のリリースまで進め、launchd の
`task watch` の再起動と Kiro IDE の定義のコピーし直しもまとめて行います。[docs/setup.md](docs/setup.md#インストール))。

## テスト

全部のテストは GitHub Actions の `macos` で動かします。使うのは GitHub の Mac です。
手元の Mac では、変えたところに関係する短いテストだけを動かします。
PR(外の fork も含む)、main への push、Actions からの手動実行で動きます。
同じ PR やブランチで新しい実行が始まると、古い実行は取り消します。

- Python の全部のテスト(CLI、インストーラ、Rust TUI の PTY テストも含む)
- Rust のビルドとテスト(Cargo のキャッシュを使う)
- Kiro の拡張の `npm test`
- B の実行役(`durable/`)の `npm test`(`npm ci` のあと。続く Python のテストが task-hub の下でも動かす)
- Python の Ruff と差分の空白の確認

結果は PR の `macos / test` で確認します。ログは各実行の `macos-test-evidence` に 14 日残ります。
Windows の専用テストは、これまでどおり `windows` で動きます。
Claude Code の mod の `claude plugin test claude/task-board` は、Claude CLI のある環境で必要なときに確かめます。

`bin/task` と `bin/task_hub.py` は Python 3.10 以上の標準ライブラリだけで書いています。Python のテストにも追加のインストールは要りません。
手元で一部を確かめる例です。

```
python3 tests/run.py test_intake
```

テストを 1 件ずつ別のプロセスで、2 つずつ並べて動かします(約 8 分)。並べる数は `-j 4` のように指定できます。
GitHub Actions の `macos` は `-j 4` で動かします。手元の既定の 2 は変えません。
`windows` は `python -m unittest` で 1 件ずつ動かします。`-j 4` で並べると落ちるテストがあり、まだ特定できていないためです。
マシンを使い切らないよう、穏やかに動かします。

- テストのプロセスは低い優先度で動きます(Unix は `nice`、Windows は `BELOW_NORMAL_PRIORITY_CLASS`)。人の作業とエージェントの反応を落とさないためです
- 全部のテストは、1 台のマシンで同時に 1 つだけ動きます。2 つめは `waiting for the full test run ...` と 1 行出して、1 つめが終わるまで待ちます。
  ロックは一時ディレクトリの `task-hub-tests.lock` で、持ち主のプロセスが死んでいれば取り直します
- 名前を渡すと、その文字を含むテストだけを動かします(例: `python3 tests/run.py test_task`)。このときは待ちません

1 件ずつ順に動かすときは `python3 -m unittest discover -s tests -v` です(全体で 13 分ほど)。
手元で全部を動かす `python3 tests/run.py` は、人から頼まれたときだけ使います。
PR を出す前に、手元の全部のテストを繰り返す必要はありません。

```
python3 -m unittest tests.test_task.TaskTest -k feedback -v
python3 -m unittest tests.test_task.TaskTest.test_version -v
```

| テスト | 中身 |
|---|---|
| `tests/test_task.py` | `bin/task` をサブプロセスとして動かす。GitHub(`gh`)、エージェント、herdr はフェイクに置き換え、git は本物を使う |
| `tests/test_install.py` | Kiro 用のインストーラ(`kiro/install.sh` など) |
| `tests/test_run.py` | `tests/run.py` の既定の並べる数、低い優先度、全部のテストのロック、出力の文字コードで書けない失敗の表示。Windows の GitHub Actions でも動く |
| `tests/test_windows.py` | Windows だけで動く(ほかでは skip)。GitHub Actions の `windows-latest` で、push のたびに動く |
| `tests/test_brand.py` | 伝え方の土台([docs/brand.md](docs/brand.md)): 1 文が README の太字、brand.md、バナーで同じ。`tokens.css` の意味の色のコントラスト比が 4.5 以上(`python3 tests/test_brand.py --table` で表を出す)。README に運営者の私的な名前が出ない。README の構成(見出しの順がこの文書の「README の構成」の表と同じ、バナーと動く画像の置き方、特長の表の 4 枚とリンク先、alt、長さ) |
| `tests/test_site.py` | LP([site/README.md](site/README.md)): ブラウザを使わずに読む。リンクと画像の先があり、外から読み込まず、`prefers-reduced-motion` で動かない作り。1 文、機能のカード 8 枚、8 つの層が brand.md と同じ。運営者の私的な名前が出ない |
| `tests/test_media.py` | `assets/media/` の画像([docs/media.md](docs/media.md)): 全部あり、大きさが上限の内で、写る文字とメタデータに運営者のボード、手元のパス、日付、メールアドレスがない。画像の元の架空のカードが、2 回動かして同じ文字になる |
| `tests/test_bench.py` | `tests/bench.py` が本物の HOME に触れず、`gh` を呼ばずに表と合否を出すこと |
| `tests/test_durable_bench.py` | `tests/durable_bench.py` の 63 回の試行の組み合わせと、`--report` の表(モデルは呼ばない) |
| `tests/test_task_rs.py` | `task-rs tui` の `g` キーと読む画面(Enter、`d`、`l`、スクロール、ログの追従、Issue のコメントと Markdown、コメントの開閉と `n` `p`)。task-rs を cargo でビルドし、PTY の中で偽物の Lazygit、偽物の gh と一時的な HOME で動かす。cargo がない、または Windows では skip |
| `durable` の `npm test` | B の実行役(実験)。pi-ai の faux provider で、ツールの途中の kill -9 からの再開、ロック、`restart_limit`、ログイン。Node.js 22.19 以上で、先に `npm ci --ignore-scripts`([durable/README.md](durable/README.md)) |
| `kiro/board-extension` の `npm test` | Kiro IDE の拡張。Node.js 22.18 以上か 23.6 以上([docs/kiro-ide.md](docs/kiro-ide.md)) |

- バグを直すときは、まず使う人から見た動きで再現するテストを書き、失敗するのを見てから直します
- テストは GitHub やエージェントの本物を呼びません。外部とのやりとりは、`tests/test_task.py` の先頭にあるフェイクに
  足します
- フェイクは本物より寛容です。GitHub やエージェントとのやりとりを変えたときは、本物で一度動かして確かめ、PR の本文に
  そう書きます([docs/lessons.md](docs/lessons.md))
- Windows で動きが変わる部分(プロセス、パス、シェル)は、`bin/task_hub.py` の `WINDOWS` で分けます
  ([docs/windows.md](docs/windows.md))

## README と docs の書き方

README は英語の `README.md`(GitHub が最初に出す)と日本語の `README.ja.md` の 2 つです。`docs/` は日本語です。
読むのは、task-hub を使う人と、このリポジトリで作業するエージェントです。

- 結論を先に書きます。前置きは書きません
- 1 文は短くします(目安は 40 字)。1 文に要点を詰め込みません
- 同じものには、毎回同じ語を使います(カード、タスク、Issue、worktree など)。途中で言い換えません
- 3 つ以上の並び、手順、比較は、箇条書きか表にします
- ハイフンは半角の `-` を使います。em ダッシュや en ダッシュは使いません
- コマンド、ファイル名、設定のキーは `` ` `` で囲みます
- 確かめていないことは、確かめていないと書きます。いつ、何で確かめたかを添えます(例: 「2026-10-01 の試験では未確認」)
- 使い方が変わる変更は、同じ PR で README と関係する docs も直します。コマンドを足したら、README の「コマンド」の表と
  `task help` の両方に出します
- README は 2 つとも同じ PR で直し、中身と見出しの順をそろえます。英語は短い文、能動態、同じものには同じ語で書きます

### README の構成

README は、初めて来た人が最初の画面で「何か」「なぜ使うか」「どう始めるか」をつかむためのページです。
詳しいことは docs に置き、README からリンクします。2 つの README の `# task-hub` の下には、
言語の切り替え(`English | [日本語](README.ja.md)`、`[English](README.md) | 日本語`)を置きます。

長さは、絵の HTML(`<picture>` と `<table>` の中)を除いて 180 行前後、多くても 200 行です。絵は読む行ではないので数えません。
コマンドの表(全部のコマンド)と docs の表が長いので、150 行前後には収まりません(2026-10-29 に決めた)。
200 行を超えそうなら、まず docs に移せるものを探します。`tests/test_brand.py` が数えます。

| 順 | 見出し(README.ja.md / README.md) | 中身 |
|---|---|---|
| 1 | `# task-hub` | 見出しの上にバナー(`assets/brand/`、ダークとライトを `<picture>` で出し分ける)。見出しの下に言語の切り替え、太字の一言の説明([docs/brand.md](docs/brand.md) の 1 文を同じ文のまま)、動く画像(`assets/media/`。`prefers-reduced-motion` なら止まった画像)、LP(`https://jyoka.github.io/task-hub/`、[site/README.md](site/README.md))への 1 行のリンク、CI のバッジ、人が決める 2 つのこと、Kiro IDE の人への案内 |
| 2 | `## しくみ` / `## How it works` | 6 段階くらいの Mermaid の図 1 枚と、箇条書き 3 つ |
| 3 | `## 特長` / `## Features` | 画面 4 枚の 2 列の表(各画像に太字の名前と 1 行の説明。画像は docs の該当の節へのリンク)、「どの画像も task-hub が自分で撮った」の 1 行、1 行ずつの箇条書き 7 つまで |
| 4 | `## はじめる` / `## Get started` | 必要なもの、コマンド 3 つ前後、最小の設定。詳しくは setup.md へ |
| 5 | `## 使い方` / `## Usage` | 3 通りの使い方の表と、頼んでからマージまでの例 1 つ。詳しくは usage.md へ |
| 6 | `## タスクの一生` / `## Task lifecycle` | 列ごとの表(何が起きているか、あなたの対応) |
| 7 | `## コマンド` / `## Commands` | 公開しているコマンドすべてを 1 行ずつ。フラグの全部は `task help` に任せる |
| 8 | `## ドキュメント` / `## Documentation` | はじめる・使う・仕組み・開発する の 4 列の表(ほかの docs がこの見出しにリンクしている) |
| 9 | `## バグ報告と要望` / `## Bug reports and feature requests` | `task feedback`、Discussions、SECURITY.md |
| 10 | `## ライセンス` / `## License` | [LICENSE](LICENSE) へのリンク 1 行 |

- 版の番号や変更の履歴は README に書きません。リリースノートに書きます([docs/release.md](docs/release.md))
- コマンドを足したら、2 つの README の「コマンド」の表に 1 行ずつ足します。表に全部のコマンドがあることはテストが確かめます
- 新しい見出しを足したくなったら、まず docs のどこかに置けないかを考えます
- 画像は `assets/media/` の、task-hub が自分で撮ったものだけを使います([docs/media.md](docs/media.md))。alt には、絵の中身が分かる文を
  2 つの README のそれぞれの言葉で書きます。ファイル名や「スクリーンショット」だけにしません
- 見出しの順、上の部分の並び、特長の表、長さは `tests/test_brand.py` が、この表と突き合わせて確かめます

置き場所の目安です。

| 内容 | 場所 |
|---|---|
| 何ができるか、使い方の全体、コマンドの一覧 | [README.md](README.md)、[README.ja.md](README.ja.md) |
| タスクの頼み方、設定、役割、手元に残るもの | [docs/usage.md](docs/usage.md) |
| セットアップ、エージェント、運用、形式 | `docs/` の各ページ([README の「ドキュメント」](README.ja.md#ドキュメント)) |
| なぜこの作りなのか | [docs/design.md](docs/design.md) |
| 作って試して分かったこと | [docs/lessons.md](docs/lessons.md) |

`bin/task` と `bin/task_hub.py` のコード、コメント、コマンドの出力は英語です。周りのコードの書き方に合わせてください。
