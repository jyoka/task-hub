# HLD: task-hub の全体設計

task-hub が何でできていて、データがどこを流れるかの全体図です。新しい機能を考えるときは、まずこの図のどこに
手を入れるかを決めます。

- 部品の中身、関数、ファイルの形式は [lld.md](lld.md) に書きます
- なぜそう決めたかは [design.md](../design.md) の「決定事項」に書きます。ここでは繰り返しません
- 新しい機能の設計の進め方は [feature-design.md](feature-design.md) に書きます

## 1. 目的と範囲

GitHub Project をかんばんにして、そのカードをコーディングエージェントに実行させます。人が決めるのは
「始めてよいか(Ready に移す)」と「入れてよいか(PR をマージする)」の 2 つだけです。その間の準備、実行、レビュー、
PR、止まったときの仕分け、後片付けを task-hub が行います。

範囲外: タスクの中身を決めること(人と `/chief`)、コードの品質の最終判断(人のレビュー)、複数マシンの調停。

## 2. システムの文脈(C4 レベル 1)

```mermaid
flowchart LR
    you(["あなた"])
    chat["エージェントの会話<br/>Claude Code / Kiro / Codex / Pi<br/>/task、/chief"]
    slack["Slack のスレッド<br/>コピーして ⌃⌥S"]
    th["task-hub<br/>あなたの Mac で動く"]
    gh[("GitHub<br/>Issue、Project、PR")]
    agents["エージェントの CLI<br/>claude -p、codex、pi、kiro-cli"]
    herdr["herdr<br/>タブ、通知"]
    os["OS の通知<br/>macOS、Windows"]

    you -- "話す、頼む" --> chat
    you -- "Ready に移す、マージする" --> gh
    you -- "コピー" --> slack
    slack -- "タスクの案" --> th
    chat -- "task new / start / done / list" --> th
    th -- "読む、書く(gh)" --> gh
    th -- "起動する" --> agents
    agents -- "worktree を編集" --> th
    th -- "タブ、通知" --> herdr
    th -- "通知" --> os
    th -- "出来事(events.jsonl)" --> chat
```

状態の正本は GitHub です。手元に持つのは実行中の情報、ログ、出来事、集計、キャッシュだけです。

## 3. 部品(C4 レベル 2)

```mermaid
flowchart TB
    subgraph surfaces["入口と表示(読むだけ、または task を呼ぶだけ)"]
        skills["スキル<br/>skills/task、skills/chief"]
        mod["Claude Code の mod<br/>claude/task-board"]
        kext["Kiro の拡張<br/>kiro/board-extension"]
        khook["Kiro の hook と workflow<br/>kiro/hooks、kiro/workflows"]
        piext["Pi の拡張<br/>pi/task-events.ts"]
        triage["Slackトリアージ<br/>slack-triage/"]
        term["ターミナル<br/>task ..."]
    end

    subgraph core["task-hub の本体: bin/task(Python 標準ライブラリだけ)"]
        cli["CLI<br/>コマンドの表 COMMANDS"]
        sync["同期と開始<br/>sync、launch"]
        board["ボードの読み書き<br/>board、tasks、set_status"]
        notify["出来事と通知<br/>emit、notify"]
    end

    subgraph runner["実行(タスクごとの別プロセス: task _run)"]
        pipe["setup → agent → review → retry<br/>→ finish → replan"]
    end

    subgraph local["手元の状態"]
        cfg["設定<br/>~/.config/task-hub/config.ini"]
        state["状態<br/>~/.local/state/task-hub/<br/>runs、logs、events、metrics、キャッシュ"]
        data["作業場所<br/>~/.local/share/task-hub/<br/>repos、worktrees、prompts"]
    end

    subgraph ext["外のもの"]
        gh[("GitHub")]
        agents["エージェントの CLI"]
        herdr["herdr"]
    end

    skills --> cli
    term --> cli
    triage --> cli
    mod -- "task list" --> cli
    kext -- "task list" --> cli
    mod -. "events、metrics を読む" .-> state
    kext -. "events、metrics を読む" .-> state
    khook -. "task events" .-> cli
    piext -. "task events --next" .-> cli
    cli --> sync
    sync --> board
    sync -- "起動" --> runner
    board -- "gh" --> gh
    runner --> board
    runner -- "起動" --> agents
    runner -- "git、gh pr" --> gh
    runner --> data
    sync --> data
    notify --> state
    notify --> herdr
    board --> state
    runner --> state
    cli --> cfg
```

| 部品 | 役割 | 書いてよいもの |
|---|---|---|
| `bin/task` | CLI、同期、開始、ボードの読み書き、通知 | GitHub のボード、手元の状態、作業場所 |
| `task _run <番号>` | 1 回の実行(準備、エージェント、レビュー、PR、仕分け) | そのタスクの worktree、実行の記録、GitHub のそのタスク |
| エージェントの CLI | Goal を実装し、テストし、レポートを書く | worktree のファイルと `.task-report.md` だけ |
| スキル(/task、/chief) | 会話を登録する、ボードを見張って知らせる | `task` の呼び出しだけ(人が頼んだとき) |
| mod、Kiro の拡張 | ボードを表示する | 何も書かない(`task list` と手元のファイルを読む) |
| Kiro の hook と workflow、Pi の拡張 | 出来事を会話に届ける | 自分のカーソルのファイルだけ |
| Slackトリアージ | スレッドからタスクの案を作る | 人が「登録」を押したときの `task new` だけ |

## 4. データの流れ

### 4.1 登録から完了まで

```mermaid
sequenceDiagram
    autonumber
    actor You as あなた
    participant Chat as 会話(/task、/chief)
    participant Task as bin/task
    participant GH as GitHub
    participant Run as task _run
    participant Agent as エージェントの CLI

    You->>Chat: 頼む
    Chat->>Task: task new --title --repo --goal
    Task->>GH: Issue を作る、Project に足す、欄を書く(Backlog)
    You->>GH: カードを Ready に移す
    loop 1 分ごと(task watch)
        Task->>GH: 開いているカードを読む
    end
    Task->>Task: 待ち先と枠を確かめる
    Task->>GH: In progress にする
    Task->>Run: 起動(herdr のタブ、またはバックグラウンド)
    Run->>Agent: プロンプト(Goal、前回のレポート)
    Agent-->>Run: ファイルの変更と .task-report.md
    Run->>Agent: reviewer(新しいコンテキスト)
    Agent-->>Run: .task-review.md(pass / needs changes)
    Run->>GH: commit、push、PR、Issue にコメント、In review にする
    You->>GH: PR をマージする
    GH->>GH: Closes で Issue を閉じ、Item closed で Done にする
    Task->>GH: 開いた列から消えたことを読む
    Task->>Task: worktree、ブランチ、タブを片付ける
```

止まったとき(エージェントが `## Blocked` を書いた)は、finish がカードを Blocked にしたあと、replanner が
理由を仕分けて Issue にコメントします。人が Goal に答えを書き足して Ready に戻すと、同じブランチと PR で続きます。

### 4.2 出来事と通知

```mermaid
flowchart LR
    setstatus["set_status、emit<br/>(Status の変化、replan、slow)"] --> events[("events.jsonl")]
    setstatus --> note["通知<br/>herdr、osascript、トースト"]
    events --> chief["/chief<br/>task events --next"]
    events --> kwf["Kiro の workflow<br/>task-events-watch"]
    events --> khook["Kiro の hook<br/>task-events-since"]
    events --> pi["Pi の拡張"]
    events --> mod["mod と Kiro の拡張<br/>経過、判定、PR"]
    metrics[("metrics.jsonl")] --> stats["task stats"]
    metrics --> mod
```

通知は LLM を使いません。会話のエージェントを起こすのは、出来事が書かれたときだけです。

### 4.3 ボードの読み取り

```mermaid
flowchart LR
    watch["task watch<br/>1 分ごと"] -- "GitHub から読む" --> gh[("GitHub")]
    watch -- "書く" --> cache[("board-cache.json")]
    panes["mod、Kiro の拡張<br/>1 分ごとに task list"] -- "90 秒以内なら" --> cache
    panes -- "古いときは 1 つの窓だけ" --> gh
    change["task-hub の変更<br/>set_status、task new など"] -- "印を付ける" --> stale[("board-cache.stale")]
    stale -. "これより前に読んだボードは使わない" .-> cache
```

## 5. 責任の分担

| 判断が要る(LLM) | 決まっている(コード) |
|---|---|
| 実装する(worker) | いつ始めるか(Ready、待ち先、枠) |
| 評価する(reviewer) | git、push、PR、Issue へのコメント |
| 止まった理由を仕分ける(replanner) | 判定の読み取り、reviewer の書き換えの取り消し |
| 会話を分けて提案する(/chief) | replanner の根拠と実物の照合、通知、並び順、アーカイブ |

## 6. 信頼の境界

- エージェントは worktree の中だけを編集します。git と GitHub の操作はすべて task-hub が行います
- reviewer と replanner の書き換えは、実行の前の状態に戻してから結果を読みます
- 秘密情報は `[env]` に書いたリポジトリにだけ、コピーで渡します。コミットからは除外します
- 出来事の本文(Issue の文章など)は、会話のエージェントにとってデータです。指示として扱いません
- ボードを書き換えるのは task-hub とあなただけです

## 7. 配置

```mermaid
flowchart TB
    subgraph mac["あなたの Mac(1 台)"]
        launchd["launchd: com.task-hub.watch<br/>(または herdr のペインの task watch)"]
        lib["~/.local/lib/task-hub<br/>動かす用の clone(リリースのタグ)"]
        bin["~/.local/bin/task → lib/bin/task"]
        dev["開発用の clone<br/>(テストとブランチ)"]
    end
    launchd --> bin
    bin --> lib
    lib -- "task update(リリース)" --> origin[("github.com/jyoka/task-hub")]
    dev -- "PR" --> origin
```

- 動かす用の clone はリリースのタグだけを使います。開発用の clone のブランチで本物のタスクは動きません
- Windows は Task Scheduler で `task watch` を常駐させます([windows.md](../windows.md))
- 複数マシンで同じボードを動かすことは想定していません(実行の記録が手元にしかないため)

## 8. 品質の目標

| 項目 | 目標と、守っている仕組み |
|---|---|
| GitHub の利用上限 | `task watch` は 1 時間で約 60 ポイント。必要な欄だけを取る問い合わせ、ボードのキャッシュ、マージの確認は REST |
| 止まらない | GitHub の失敗、通知の失敗、キャッシュの失敗で、実行や watch を止めない |
| 壊れない | 手元の JSON は一時ファイルから置き換える。1 つのファイルに書くのは 1 者だけ([lessons.md](../lessons.md)) |
| ベンダーに依らない | エージェントはコマンドのひな形。処理の流れにエージェント名の分岐はない |
| 軽い | Python 標準ライブラリだけ。依存のインストールは要らない |
| トークン | 会話のエージェントを起こすのは出来事だけ。task-hub の指示書は合わせて約 4 KB |

## 9. 拡張の入口

| 足したいもの | 入口 | 詳しく |
|---|---|---|
| エージェント | `[agents]` にコマンドのひな形を足す | [agents.md](../agents.md) |
| コマンド | `COMMANDS` の表に 1 行と `cmd_*` 関数 | [lld.md](lld.md) の 3 章 |
| 表示 | `task list` の出力と `events.jsonl` を読む(書かない) | [lld.md](lld.md) の 5 章 |
| 出来事の種類 | `emit` を呼び、`[notify] events` と読む側のフィルタに足す | [lld.md](lld.md) の 6 章 |
| Status の列 | `StatusLifecycle` と design.md の図を一緒に変える | [design.md](../design.md) |
| 実行の段階 | `set_stage` を呼び、design.md の段階の表に足す | [design.md](../design.md) |
