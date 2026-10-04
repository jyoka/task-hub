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

## テスト

`bin/task` は Python 3.10 以上の標準ライブラリだけで書いています。テストも同じで、インストールは要りません。

```
python3 -m unittest discover -s tests -v
```

全体で 11 分ほどかかります。作業中は、変えた部分のテストだけを動かすと速く済みます。

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

置き場所の目安です。

| 内容 | 場所 |
|---|---|
| 何ができるか、使い方の全体、コマンドの一覧 | [README.md](README.md) |
| セットアップ、エージェント、運用、形式 | `docs/` の各ページ([README の「ドキュメント」](README.md#ドキュメント)) |
| なぜこの作りなのか | [docs/design.md](docs/design.md) |
| 作って試して分かったこと | [docs/lessons.md](docs/lessons.md) |

`bin/task` のコード、コメント、コマンドの出力は英語です。周りのコードの書き方に合わせてください。
