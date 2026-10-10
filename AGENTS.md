# AGENTS.md

このリポジトリ(task-hub)で作業するエージェントへの案内です。人向けの決まりは [CONTRIBUTING.md](CONTRIBUTING.md)
にあり、ここはその入口です。食い違ったら CONTRIBUTING.md が正です。

task-hub を使いはじめるために、このリポジトリを開いて「セットアップして」と頼まれたときは、開発ではありません。
[.kiro/steering/setup.md](.kiro/steering/setup.md) の手順に従います。

## まず読むもの

| 知りたいこと | 読むもの |
|---|---|
| 全体の部品とデータの流れ | [docs/architecture/hld.md](docs/architecture/hld.md) |
| 関数、プロセス、ファイル、外部の呼び出し、守る約束 | [docs/architecture/lld.md](docs/architecture/lld.md) |
| なぜこの作りなのか | [docs/design.md](docs/design.md) の「決定事項」、[docs/lessons.md](docs/lessons.md) |
| 機能を足す前の設計 | [docs/architecture/feature-design.md](docs/architecture/feature-design.md)(Claude Code なら `system-designer` エージェント) |

## 書き方

- `bin/task` のコード、コメント、コマンドの出力は英語。周りのコードに合わせる。Python 3.10 以上の標準ライブラリだけ
- README と `docs/` は日本語。書き方は [CONTRIBUTING.md の「README と docs の書き方」](CONTRIBUTING.md#readme-と-docs-の書き方)
- README の構成は決まっている([CONTRIBUTING.md の「README の構成」](CONTRIBUTING.md#readme-の構成))。詳しいことは
  README に足さず、docs に置いてリンクする
- 使い方が変わる変更は、同じ PR で README と関係する docs も直す。部品、流れ、ファイル、外部の呼び出しが変わるなら
  `docs/architecture/` の HLD と LLD も直す

## 確かめ方

```sh
python3 tests/run.py                       # Python のテスト全部(並列、約 3.5 分)
python3 tests/run.py <名前の一部>          # 一部だけ
claude plugin test claude/task-board       # Claude Code の mod
(cd kiro/board-extension && npm test)      # Kiro の拡張
```

不具合は、利用者から見た動きを再現するテストを先に書いてから直す。

## してはいけないこと

- 引数なしの `task`、`task watch`、`task start` を本物のボードに向けて動かさない(Ready のカードが始まる)。
  確かめるのはテストの偽物の GitHub で行う。本物で読むだけなら `task list`
- `~/.local/lib/task-hub`(動かす用の clone)を編集しない。作業はこのリポジトリのブランチで行う
