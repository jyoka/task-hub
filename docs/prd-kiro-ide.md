# PRD: Kiro IDE 版 task-hub (2026-10-01)

## 1. 背景

- 仕事用の Mac では Kiro しか使えません (docs/design.md の制約)。そこでは IDE が作業の中心で、herdr やターミナルを
  開いたままにする前提が成り立ちません。
- IDE 対応の調べもの 3 件の結果がこの PRD の前提です:
  - tasks#22 (調べもの): `/task` は Kiro IDE から使える見込み。`/chief` の見張りは IDE では確かめられず、
    通知で代わりにする
  - tasks#23 (PR jyoka/task-hub#2): `task open <番号>` で worktree を `[ide] open` のコマンドで開く
  - tasks#24 (PR jyoka/task-hub#1): `task watch` を launchd で常駐させる手順
- 2026-10-01 に Kiro の公式ドキュメントで追加の調査をしました (下の「Kiro IDE で使える仕組み」)。

## 2. 目的

Kiro IDE を **操作席** にし、Kiro だけで task-hub の一周 (登録 → 承認 → 実行 → 知らせ → レビュー → マージ) を回せるようにします。

| # | ユーザーが IDE でしたいこと | 今 |
|---|---|---|
| G1 | チャットで `/task` と言ってタスクを登録する | 使える見込み (#22)。実機は未確認 |
| G2 | In review、Blocked などを、IDE のチャットで知る | macOS の通知だけ。チャットには届かない |
| G3 | 止まったタスクの worktree を Kiro IDE で開く | #23 (未マージ) で `[ide] open = kiro {path}` にすればできる |
| G4 | IDE を閉じても、Ready のカードが始まる | #24 (未マージ) の launchd の手順。kiro-cli の PATH とキーが要る |
| G5 | 実行は kiro-cli に固定し、無人で止まらず動く | `agent = kiro` はできる。無人でのログインの保ち方は未確認 |
| G6 | Kiro のクレジットの使い過ぎに気づく | Kiro の使用量は記録していない (docs/agents.md) |

## 3. やらないこと

- IDE の拡張機能 (サイドバーのボードなど)。ボードは GitHub Project の画面を使います
- Kiro の Spec (`.kiro/specs/`) との連携
- `bin/task` を Kiro 専用に分けること。**`bin/task` は 1 つのまま** で、Kiro 用のものは設定、フック、スクリプト、
  ドキュメントとして足します (シンプルさのルール 3: 1 つのことをする方法は 1 つ)
- kiro-cli 以外のエージェントでの確認 (ベンダー中立の作りは壊さないが、この PRD では試さない)

## 4. Kiro IDE で使える仕組み (2026-10-01 の調査、公式ドキュメント)

| 仕組み | 使えること | 制限 |
|---|---|---|
| Skills (`~/.kiro/skills/`) | IDE と CLI で共通。`/` で呼べる | `disable-model-invocation` は載っていない。IDE では `$ARGUMENTS` の置き換えがない |
| Steering (`~/.kiro/steering/`) | `inclusion: always / auto / manual / fileMatch` | |
| Hooks (`.kiro/hooks/*.json`、`~/.kiro/hooks/` は IDE 1.0.182 から) | Prompt Submit、Agent Stop などで **シェルコマンド** を LLM なしで実行し、標準出力をエージェントの文脈に足す | タイマーや外部の出来事で動くトリガーはない。トリガー名の表記はページで違うので実物で確かめる |
| Workflows (IDE 1.2、設定で有効化) | `watch` ノードの `handler: command` がスクリプトを定期実行 (既定 60 秒) し、待っている間はモデルを使わない。スクリプトは `{outcome: idle / new-activity / terminal-state, cursor, payload}` を 1 つ出す | 新しい機能。実機での確認が要る |
| `kiro <path>` | フォルダを Kiro IDE で開く | 新しいウィンドウの `-n` は載っていない |
| kiro-cli のヘッドレス実行 | `--no-interactive --trust-all-tools`。無人では `KIRO_API_KEY` (Pro 以上) が確実 | クレジットは IDE、CLI、Web で共通 |

出典: kiro.dev/docs/skills、/steering、/hooks、/hooks/types、/hooks/actions、/workflows、/workflows/authoring、
/ide/setup、/cli/headless、/getting-started/authentication、/pricing、changelog/ide/1-0-182、/1-2。

## 5. 方針

1. **出来事は `task events` のカーソル 1 つで渡します。** 今の `--next` は待つので、フックや Workflows からは使えません。
   `--after N` を待たずに返す形にも使えるようにし、フックと Workflows の両方がそれを呼ぶだけにします
   (出来事のファイルは 1 つ、読み方は 1 つ)。
2. **チャットに届けるのは 2 段構えです。**
   - 話しかけたとき: Prompt Submit のフックが、前回からの出来事を文脈に足します (LLM の呼び出しは増えない)
   - 話しかけていないとき: Workflows の `watch` が待ち、出来事が来たら `/chief` に渡します (待つ間はクレジットを使わない)
   - どちらも動かなくても、macOS の通知は今までどおり届きます
3. **実行は kiro-cli に固定し、始める前に確かめます。** ログインかキーがなければ、エージェントを起動する前に理由を書いて
   Blocked にします (クレジットを使う前に止める)。
4. **Kiro 用の部品はリポジトリの `kiro/` にまとめ、手順は `docs/kiro-ide.md` 1 つにします。**

## 6. PBI

jyoka/tasks に Backlog として登録済みです (2026-10-01)。

| Issue | タイトル | 種類 | 待ち先 |
|---|---|---|---|
| #41 | Kiro IDE 版 (1/5): 話しかけたときに新しい出来事を差し込むフック | 実装 | なし |
| #44 | Kiro IDE 版 (2/5): /chief を Kiro Workflows の watch で起こす | 実装 | #41 |
| #42 | Kiro IDE 版 (3/5): kiro-cli を無人で動かす(事前確認と環境変数) | 実装 | なし |
| #43 | Kiro IDE 版 (4/5): kiro-cli のクレジット消費を記録する方法を調べる | 調べもの | なし |
| #45 | Kiro IDE 版 (5/5): セットアップ手順 docs/kiro-ide.md と steering | ドキュメント | #23、#24、#41、#44、#42 |

## 7. 人が実機で確かめること (エージェントは IDE の画面を動かせない)

1. Kiro IDE のチャットで `/task` が候補に出て、`task new` まで動くか (G1)
2. `disable-model-invocation` がない Kiro で、`/task` を頼んでいないのに登録しようとしないか
3. Prompt Submit のフックの出力が、実際にチャットの文脈に入るか (PBI 1)
4. Workflows の `watch` で、出来事が `/chief` のチャットに届くか (PBI 2)
5. `kiro -n <path>` で新しいウィンドウが開くか (G3)
6. launchd から動かした `task watch` で、kiro-cli が無人で動き続けるか (G4、G5)

## 8. 成功の基準

- 仕事用の Mac で、ターミナルを開かずに 1 つのタスクを登録からマージまで回せる
- In review と Blocked を、IDE のチャット (話しかけたとき、または `/chief`) と macOS の通知の両方で知れる
- ログインが切れているとき、クレジットを使う前に理由つきで Blocked になる
- 既存のテストがすべて通り、ほかのエージェントの動きが変わらない
