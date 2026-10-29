# 伝え方: 1 文、機能の文、見た目、バナー

task-hub を外に伝えるときの土台です。README の絵、画像、LP を作るカードは、まずこれを読みます。

- 状態: 1 文、誰のためか、機能の文、分解の絵の台本、見た目、バナーを決めた(2026-10-29)
- 置き場所: この文書と [`assets/brand/`](../assets/brand/)(`tokens.css`、`banner-dark.svg`、`banner-light.svg`)
- お手本は tuios の作りと書き方。文、絵、ロゴは写さない
- 例のデータは、どれも架空。本物のボード、Issue、リポジトリの名前は使わない(7 節)

## 結論

- 1 文は「**Ready に移した GitHub Project のカードを、手元のエージェントがレビュー済みの PR にする。**」。
  英語は「**Your local coding agents turn each GitHub Project card you move to Ready into a reviewed PR.**」
- この 1 文を、README の太字、バナー、LP の見出し、GitHub の About で、同じ文のまま使う。変えるときは全部を一度に変える
- 機能は、名詞の見出しと 2 行の説明のカード 8 枚で伝える(3 節)。形容詞を使わず、コマンド、設定、数で書く
- 分解の絵は、1 枚のカードの一生を 8 つの層に分ける。層の色は「誰がするか」(あなた、task-hub のコード、エージェント)を表す(4 節)
- 見た目は [`assets/brand/tokens.css`](../assets/brand/tokens.css) の CSS の変数で決める。意味の色は、どれもコントラスト比 4.5 以上(5 節)
- README の例の Issue `jyoka/tasks#12` は、このカードで `you/tasks#12` に直した。docs に残る私的な名前は 7 節の一覧にした

## 1. 1 文

task-hub が何で、何が違うかを 1 文で言い切る。

### 案

| 案 | 日本語 | 英語 | 判断 |
|---|---|---|---|
| A | Ready に移した GitHub Project のカードを、手元のエージェントがレビュー済みの PR にする。 | Your local coding agents turn each GitHub Project card you move to Ready into a reviewed PR. | **採る** |
| B | 決めるのは Ready とマージの 2 つだけで、その間は手元のエージェントが進める。 | You decide two things, Ready and merge, and your local coding agents do the rest. | 見送る。GitHub も PR も出てこず、初めての人には「Ready」が何か分からない。README の 2 行目(人が決める 2 つ)に任せる |
| C | GitHub Project のボードを、手元のコーディングエージェントの仕事の列にする。 | Turn a GitHub Project board into the work queue for the coding agents on your machine. | 見送る。何が出てくるか(PR)と、PR の前のレビューが抜け、違いが伝わらない |

### A を選んだ理由

- 何か: GitHub Project のカードから PR を作る道具だと分かる
- 何が違うか: 「手元の」で、クラウドではなく自分の Mac のエージェント CLI が動くことを言う。「レビュー済みの」で、
  PR の前に別のエージェントが確かめることを言う。今の文にはこの 2 つ目がない
- 何をすればよいか: 「Ready に移した」で、人がする操作が 1 つだと分かる
- 長さ: 日本語で 51 字(空白を除く)。目安の 40 字を超えるが、「GitHub Project」を抜くと何の道具かが分からなくなるので残した
- 気をつけること: 「レビュー済み」は `[runner] reviewer` を書いたときの話。README の「はじめる」の最小の設定には書いてある。
  既定(空)ではレビューしない([usage.md](usage.md) の「設定」)

### 今の文との比べ

| 場所 | 今の文 | 違い |
|---|---|---|
| README の太字(英語) | Move a GitHub Project card to Ready. Your local coding agent implements it and opens a PR. | 2 文。レビューが出てこない。このカードで A に直した |
| README の太字(日本語) | GitHub Project のカードを Ready に移すと、手元のコーディングエージェントが実装して PR を出す。 | 同上。このカードで A に直した |
| GitHub の About | Move a GitHub Project card to Ready; your local coding agent (Claude Code, Codex, Pi, Kiro) implements it and opens a PR | README の文と少し違う。エージェントの名前の並びは、増えるたびに直すことになる |

GitHub の About は運営者が変える。案は A の英語をそのまま使う:
`Your local coding agents turn each GitHub Project card you move to Ready into a reviewed PR.`
エージェントの名前は、README の 2 段落目(「Any agent CLI with a non-interactive mode works」)と About の Topics に任せる。

### 使う場所

| 場所 | 使う文 |
|---|---|
| `README.md` の太字 | 英語 |
| `README.ja.md` の太字 | 日本語 |
| バナー(6 節) | 両方 |
| GitHub の About | 英語(運営者が変える) |
| LP の見出し、フッター、`llms.txt` | 日本語と英語(LP のカードで作る) |

[`tests/test_brand.py`](../tests/test_brand.py) が、2 つの README の太字、この文書、2 枚のバナーの文が同じかを確かめる。

### 英語の言葉

英語で書くときは、次の語を使う。README と同じ語にしている。

| 日本語 | 英語 |
|---|---|
| カード | card |
| タスク | task |
| ボード | board |
| 手元のエージェント | local coding agent |
| 新しい文脈のレビュー、自動レビュー | fresh-context review、automated review |
| 受け入れ条件 | acceptance criterion |
| 差し戻し | send back |
| マージの順番待ち | merge queue |
| 止まった理由の仕分け | sorting out why a task stopped |
| 前後関係 | dependency |

## 2. 誰のためか、なぜ task-hub か

| | 日本語 | English |
|---|---|---|
| 誰のためか | GitHub の Issue と PR で開発し、Claude Code、Codex、Pi、Kiro などのエージェント CLI を自分の Mac で使っている人。 | People who build with GitHub Issues and PRs and run an agent CLI (Claude Code, Codex, Pi, Kiro, and others) on their own Mac. |
| 何が楽になるか | 人がするのは、カードを Ready に移すことと、PR をマージすることだけ。その間の実装、テスト、新しい文脈のレビュー、PR、止まった理由の仕分けは、task-hub とエージェントが進める。 | You move a card to Ready and merge the PR. task-hub and your agents do the rest: implement, test, review in a fresh context, open the PR, and sort out why a task stopped. |
| 何が分かるか | どのカードも、Issue にレポートとレビューの判定が残り、ボードの列で今どこにいるかが分かる。`[autopilot]` を書いたリポジトリでは、自動レビュー(`review_mode = goldfish` なら 2 つの視点)に合格した PR が、マージキューでマージまで進む。 | Each card leaves its report and review verdict on the Issue, and its column shows where it is. For repositories under `[autopilot]`, a PR that passes the automated review (two viewpoints with `review_mode = goldfish`) goes through the merge queue to the merge. |

## 3. 機能のカード 8 枚

書き方の決まり:

- 見出しは名詞 2〜3 語。形容詞を使わない
- 説明は 2 行。1 行目は何ができるか、2 行目は具体(コマンド、設定、数)
- カードの絵は task-hub の本物の画面(テストの偽物の GitHub で作った架空のボード)にし、押すと「詳しく」の docs に飛ぶ

| # | 見出し | 説明(日本語) | Heading | Description | 詳しく |
|---|---|---|---|---|---|
| 1 | 1 タスク 1 PR | 1 枚のカードに、1 つのブランチ、1 つの worktree、1 つの PR。<br>最大 5 つを並べて動かし、ブランチは `task/<番号>`。 | One PR per task | Each card gets one branch, one worktree, and one PR.<br>Up to 5 run at the same time, on branches named `task/<id>`. | [usage.md](usage.md#見え方と手元に残るもの) |
| 2 | PR の前のレビュー | 新しい文脈のエージェントが、受け入れ条件を 1 つずつ確かめる。<br>差し戻しは既定で 2 回まで。`review_mode = goldfish` では、レポートを読まない 2 つの視点が見る。 | Pre-PR review | An agent in a fresh context checks each acceptance criterion.<br>It sends the work back 2 times at most by default. With `review_mode = goldfish`, two viewpoints that skip the report check it. | [task-format.md](task-format.md#goldfish-のレビューrunner-review_mode) |
| 3 | Goal の確認 | `task check <番号>` で、Goal とコードだけを知るエージェントが GO / NO-GO を出す。<br>NO-GO には Goal に足す文言が付く。`readiness = require` なら、GO のないカードは始まらない。 | Goal check | `task check <id>` has agents that know only the Goal and the code say GO or NO-GO.<br>A NO-GO comes with wording to add. With `readiness = require`, a card without a GO does not start. | [task-format.md](task-format.md#ready-の前の確かめtask-check) |
| 4 | 止まった後の再開 | クラッシュや再起動で止まった実行を、止まった所から 1 回だけ再開する。<br>利用の上限で止まったら、戻る時刻を書いて待ち、戻ったら同じ所から続ける。 | Stop recovery | A run that stops on a crash or a restart resumes once, from where it stopped.<br>A run that hits the usage limit waits for the reset time, then goes on from the same place. | [operations.md](operations.md#利用の上限で止まった) |
| 5 | Blocked の仕分け | 止まった理由をエージェントが仕分けて、Issue にコメントする。<br>Goal に答えを足して Ready に戻すと、同じ PR で続く。 | Blocked triage | An agent sorts out why a task stopped and comments on the Issue.<br>Add the answer to the Goal, move the card to Ready, and the same PR continues. | [agents.md](agents.md#blocked-の仕分けreplanner) |
| 6 | マージキュー | `task merge` で承認した PR を、base に追いつかせ、チェックを待ってマージする。<br>衝突はエージェントが直す。1 つのリポジトリで 1 度に 1 本。 | Merge queue | `task merge` approves a PR; the queue brings it up to date with its base, waits for its checks, and merges it.<br>An agent fixes conflicts. One PR per repository at a time. | [operations.md](operations.md#マージキュー) |
| 7 | エージェントの選択 | 非対話モードを持つエージェント CLI なら、どれでも動かせる。<br>git、PR、Issue のコメントは task-hub がコードで行うので、どのエージェントでも同じ形の PR になる。 | Agent choice | Any agent CLI with a non-interactive mode works.<br>task-hub does git, the PR, and the Issue comments in code, so every agent makes the same kind of PR. | [agents.md](agents.md#エージェントの変更と追加) |
| 8 | 通知と費用 | In review、Blocked、長い実行、予算超えを、OS の通知と ntfy で知らせる。LLM は使わない。<br>起動ごとのトークンと費用を、エージェント CLI の記録から読む(`task stats`)。 | Alerts and cost | In review, Blocked, long runs, and runs over budget show as OS notifications and on ntfy. No LLM is used.<br>Tokens and cost per launch come from the agent CLI's own records (`task stats`). | [operations.md](operations.md#通知llm-なし) |

README の「特長」の 1 行ずつの文は、上の 8 枚のもとになった。README の「特長」を直すのは、README の絵のカードで行う。

## 4. 分解の絵の台本

1 枚のカードの一生を、層に分けて見せる絵。LP の真ん中と README の「しくみ」に置く(作るのは README の絵と LP のカード)。

- 見出し: 「1 枚のカードを、層ごとに見る。」/「One card, layer by layer.」
- 絵の中身は、task-hub が自分で撮った本物の画面にする(ボード、`task list`、Issue のレポート、PR)。
  テストの偽物の GitHub(`tests/`)で、下の架空のカードを動かして撮る
- 層の色は「誰がするか」を表す。あなた(`--actor-you`)、task-hub のコード(`--actor-task-hub`)、エージェント(`--actor-agent`)。
  README の「LLM を使うのは 3 か所だけ」を、色で見せる

### 例のカード(架空)

| 項目 | 値 |
|---|---|
| ボードと Issue | `you/tasks#12`(Project は `you/1`) |
| 作業先 | `you/notes-app`(架空のメモのアプリ) |
| 題 | メモの一覧に検索欄を付ける / Add a search box to the notes list |
| 受け入れ条件 | 題名と本文から探せる。大文字と小文字を区別しない。テストがある |
| 起きること | 1 回目のレビューで「大文字と小文字を区別している」と差し戻され、2 回目で `pass` |

### 層の順と 1 行

上から下へ、1 枚ずつ離して見せる。

| 順 | 層 | 1 行 | Line | この例で見えるもの | 誰が(色) |
|---|---|---|---|---|---|
| 1 | GitHub Project のカード | あなたが Backlog から Ready に移す。始めてよい、という合図。 | You move the card from Backlog to Ready: the go-ahead. | ボードの Ready の列の `#12 メモの一覧に検索欄を付ける` | あなた(`--actor-you`) |
| 2 | task-hub の runner | `task watch` が 1 分ごとにボードを読み、空いた枠でカードを始める。 | `task watch` reads the board every minute and starts the card in a free slot. | `task list` の `In progress` と、5 つの枠のうち 1 つ | task-hub(`--actor-task-hub`) |
| 3 | worktree | カードごとのブランチと作業場所。ほかのカードと混ざらない。 | One branch and one working folder per card, apart from every other card. | ブランチ `task/12` | task-hub(`--actor-task-hub`) |
| 4 | 手元のエージェント | ファイルを編集し、テストを動かし、レポートを書く。git には触らない。 | Edits files, runs the tests, and writes a report. It never touches git. | 検索欄の変更、`.task-report.md` | エージェント(`--actor-agent`) |
| 5 | 新しい文脈のレビュー | 別のエージェントが、受け入れ条件を 1 つずつ確かめる。足りなければ差し戻す。 | Another agent checks each acceptance criterion and sends the work back if one fails. | 1 回目 `needs changes`(大文字と小文字)、2 回目 `pass` | エージェント(`--actor-agent`)。判定は `--verdict-changes`、`--verdict-pass` |
| 6 | PR | task-hub が push して PR を開き、レポートと判定を Issue に書く。 | task-hub pushes, opens the PR, and writes the report and the verdict on the Issue. | `you/notes-app` の PR、カードは In review | task-hub(`--actor-task-hub`) |
| 7 | マージの順番待ち | 承認した PR を base に追いつかせ、チェックを待つ。1 つのリポジトリで 1 度に 1 本。 | Brings the approved PR up to date with its base and waits for its checks, one per repository at a time. | `task merge 12`、`wait for merge` の列 | task-hub(`--actor-task-hub`) |
| 8 | マージ | PR が入り、Issue が閉じ、worktree が片付く。待っていたカードが始まる。 | The PR goes in, the Issue closes, and the worktree is cleaned up. Cards waiting on it start. | カードは Done | あなた(`--actor-you`)。`[autopilot]` では task-hub |

### 動きと幅

- スクロールに合わせて層を 1 枚ずつ離す。差し戻しのあった層(レビュー)だけ、`needs changes` から `pass` に変わる印を付ける
- `prefers-reduced-motion` のときは動かさない。8 層を縦に並べた止まった絵を出す
- スマホの幅では、層を縦 1 列に並べる。横に並べない

## 5. 見た目

決まりは [`assets/brand/tokens.css`](../assets/brand/tokens.css) の CSS の変数に書いた。

- 切り替え: OS の設定(`prefers-color-scheme`)に従う。`<html data-theme="dark">` か `data-theme="light"` を書くと、OS の設定より優先する
- 列の色: `--status-*` は、今の画面(`claude/task-board/hooks/panel.ts` の `STATUS_COLORS`、Kiro の拡張)と同じ意味にした。
  Blocked は赤、In review は黄、wait for merge は緑、In progress は水色
- 字: OS に入っている字だけを使う(`--font-sans`、`--font-mono`)。Web フォントは読み込まない
- 角丸: 4、6、8、12 px と丸(999 px)
- 動き: `--motion-fast`、`--motion-slow`。`prefers-reduced-motion` のときは 0 になる
- 印: 高さの違う 3 本の柱(ボードの列)。Kiro の拡張のアイコン(`kiro/board-extension/media/board.svg`)と同じ形

| 変数 | ライト | ダーク | 使う所 |
|---|---|---|---|
| `--bg` | `#f6f7f8` | `#121417` | 地 |
| `--panel` | `#ffffff` | `#1b1e23` | 板、カード |
| `--line` | `#d5d9de` | `#343a42` | 線 |
| `--text` | `#1b1f24` | `#e8eaed` | 字 |
| `--muted` | `#5c6570` | `#a0a8b2` | 添える字、Backlog |
| `--accent` | `#1f5fbf` | `#7aa7ff` | 押せる所、Ready、あなた |
| `--on-accent` | `#ffffff` | `#121417` | `--accent` の上の字 |
| `--cyan` | `#0b6e7d` | `#4cc4d4` | In progress、task-hub のコード |
| `--violet` | `#6b3fb0` | `#b493f0` | エージェント |
| `--ok` | `#1a7a3e` | `#4cc27f` | pass、wait for merge、Done |
| `--warn` | `#8a5800` | `#e6b04c` | In review、needs changes |
| `--error` | `#b42318` | `#f7786d` | Blocked、失敗 |

`*-bg` の変数(`--ok-bg` など)は、意味の色の薄い地。印の中に意味の色の字を置くときに使う。

### コントラスト比

意味の色は、どれも地(`--bg`)、板(`--panel`)、自分の薄い地(`*-bg`)に対して 4.5 以上。WCAG 2 の相対輝度で測る。
`tests/test_brand.py` が確かめ、下の表は `python3 tests/test_brand.py --table` で出す(2026-10-29)。

| 字 / 印 | 地 | ライト | ダーク |
|---|---|---|---|
| `--text` | `--bg` | 15.44 | 15.31 |
| `--text` | `--panel` | 16.56 | 13.87 |
| `--muted` | `--bg` | 5.51 | 7.68 |
| `--muted` | `--panel` | 5.91 | 6.95 |
| `--accent` | `--bg` | 5.68 | 7.73 |
| `--accent` | `--panel` | 6.09 | 7.00 |
| `--cyan` | `--bg` | 5.53 | 8.92 |
| `--cyan` | `--panel` | 5.93 | 8.08 |
| `--violet` | `--bg` | 6.61 | 7.36 |
| `--violet` | `--panel` | 7.09 | 6.66 |
| `--ok` | `--bg` | 5.02 | 8.20 |
| `--ok` | `--panel` | 5.39 | 7.43 |
| `--warn` | `--bg` | 5.63 | 9.38 |
| `--warn` | `--panel` | 6.04 | 8.50 |
| `--error` | `--bg` | 6.13 | 6.91 |
| `--error` | `--panel` | 6.57 | 6.26 |
| `--accent` | `--accent-bg` | 5.31 | 6.51 |
| `--cyan` | `--cyan-bg` | 5.21 | 7.09 |
| `--violet` | `--violet-bg` | 6.08 | 6.35 |
| `--ok` | `--ok-bg` | 4.76 | 6.68 |
| `--warn` | `--warn-bg` | 5.39 | 7.66 |
| `--error` | `--error-bg` | 5.70 | 5.99 |
| `--on-accent` | `--accent` | 6.09 | 7.73 |

色を変えたら、テストを動かし(`python3 tests/run.py test_brand`)、表を出し直してここに貼る。

## 6. バナー

- ファイル: [`assets/brand/banner-dark.svg`](../assets/brand/banner-dark.svg)、[`assets/brand/banner-light.svg`](../assets/brand/banner-light.svg)。1280 × 640(GitHub の共有の絵の大きさ)
- 中身: 印と名前 `task-hub`、1 文(日本語と英語)、分解の絵の 8 層(レビューに `pass` の印)、色の凡例(You、task-hub、Agent)
- 色は `tokens.css` の値だけを使う(`tests/test_brand.py` が確かめる)。動きはない。外から読み込むものはない
- 字は、見る人の OS の字で描かれる。字の形を固定したいとき(GitHub の共有の絵に上げるときなど)は、PNG に書き出す。書き出しはまだしていない
- 2026-10-29 に macOS の Quick Look(`qlmanage -t`)で PNG にして、字がはみ出さないことを目で確かめた。ほかの OS の字では確かめていない

README の一番上に置くときは、ダークとライトを `<picture>` で出し分ける(置くのは README の絵のカード)。

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/banner-dark.svg">
  <img alt="task-hub: Your local coding agents turn each GitHub Project card you move to Ready into a reviewed PR." src="assets/brand/banner-light.svg">
</picture>
```

## 7. 公開の前に直すもの

運営者の私的な名前が、外向けの文に出ている所の一覧。2026-10-29 に、次の検索で調べた。

```sh
rg -n -i "aica|求人|AIprogramming|ai-CA_RA|voice-(agent|resume)|LINE のトーク|jyoka/(tasks|2\b|3\b|task-sandbox)" README.md README.ja.md CONTRIBUTING.md SECURITY.md AGENTS.md docs
```

数えないもの:

- `jyoka/task-hub`: このリポジトリそのもの(public)。clone の URL、バッジ、Discussions
- `jyoka/workenv_setting`([sandbox.md](sandbox.md) の 11 行): public のリポジトリ
- `<you>/task-sandbox`、`you/tasks`、`<owner>`: 一般の言い方

### このカードで直した所

| 場所 | 前 | 後 |
|---|---|---|
| `README.md` の「Usage」の例 | `Issue jyoka/tasks#12` | `Issue you/tasks#12` |
| `README.ja.md` の「使い方」の例 | `Issue jyoka/tasks#12` | `Issue you/tasks#12` |

`tests/test_brand.py` が、2 つの README に、運営者のボード、private のリポジトリ、仕事の名前が戻っていないかを確かめる。
LP はまだない。LP のカードで、同じ確かめを LP にも足す。

### 残した所: docs(公開の前に直すか、運営者が決める)

| ファイル | 行 | 中身 | 種類 |
|---|---|---|---|
| [setup.md](setup.md) | 136、148、149 | `[env]` と `[setup]` の例に、仕事のリポジトリ `jyoka/aica_ra_a2a_poc`、手元のパス `~/AIprogramming PJ/ai-CA_RA-A2A-PoC/`、`voice-agent`、`voice-resume` | private のリポジトリ、仕事の名前、手元のパス |
| [operations.md](operations.md) | 127〜129 | `events.jsonl` の例に、`jyoka/aica_ra_a2a_poc` と題「求人検索と…」 | private のリポジトリ、仕事の名前 |
| [autopilot.md](autopilot.md) | 25 | 設定の例 `repos = jyoka/aica` | private のリポジトリ |
| [notifications.md](notifications.md) | 13、24、25 | 運営者のボード `jyoka/2` と、Issue のリポジトリ `jyoka/tasks` | 本物のボードの番号 |
| [task-format.md](task-format.md) | 5、531 | 例の `jyoka/tasks`、本物の Issue `jyoka/tasks#81` | private のリポジトリ、本物の Issue |
| [issue-tracker.md](issue-tracker.md) | 5 | 例の `jyoka/tasks` | private のリポジトリ |
| [design.md](design.md) | 110、127、394、444、457 | 本物の Issue(`jyoka/tasks#81`、`#281`、`#129〜#248`)、「aica の Render」 | 本物の Issue、仕事の名前 |
| [lessons.md](lessons.md) | 40、120、131、185〜193、244〜247、254、297、301〜311、331、371、391 | 本物の Issue の番号と題(`#224 最初の求人は…` など)、aica、`jyoka/aica_ra_a2a_poc` | 本物の Issue、仕事の名前 |
| [review-2026-10-03.md](review-2026-10-03.md) | 79、80、85、87、89 | 試験用の Project `jyoka/3`、運営者のボード `jyoka/2`、`jyoka/tasks` の Issue と `jyoka/task-sandbox` の PR へのリンク | 本物のボードの番号、private のリポジトリ |
| [release.md](release.md) | 83〜85 | CI の変数の値 `jyoka/3`、`jyoka/task-sandbox` | 本物のボードの番号、private のリポジトリ(運営者向けの手順) |
| [architecture/lld.md](architecture/lld.md) | 601 | 本物の Issue `jyoka/tasks#246` | 本物の Issue |
| [architecture/designs/autopilot.md](architecture/designs/autopilot.md) | 7 | 「大きなプロジェクト(jyoka/aica)」 | private のリポジトリ |
| [architecture/designs/team-sync.md](architecture/designs/team-sync.md) | 76、85 | 図の中の `jyoka/tasks` | private のリポジトリ |
| [architecture/designs/autopilot-unblock.md](architecture/designs/autopilot-unblock.md) | 10、32、325、342、344、358、473〜481、490、556、589、637 | 本物の Issue の番号と題(`#255 LINE のトークで直せない` など)、`jyoka/aica#114`、`jyoka/tasks#253` | 本物の Issue、private のリポジトリ、仕事の名前 |

直し方の案:

- 設定と出来事の例(setup.md、operations.md、autopilot.md、issue-tracker.md、task-format.md の 5 行): `you/app`、`~/code/app/` のような一般の言い方に直す。すぐ直せる
- 本物の Issue の番号を根拠に引く所(design.md、lessons.md、lld.md、designs/): 外の人は開けない。番号を消すか、「運営者のボードの Issue(private)」と書く。決めるのは運営者
- 運営者向けの手順(release.md、review-2026-10-03.md): 運営者の環境の話なので、残すか、`<owner>/<number>` に直すかを運営者が決める

### 参考: 運営者のアカウント名を使う架空の例

本物ではないが、運営者のアカウント名 `jyoka` を使う架空の例。外の人が見ると、運営者の本物のリポジトリと取り違えるかもしれない。

| ファイル | 行 | 中身 |
|---|---|---|
| [usage.md](usage.md) | 77、81、95〜97、106 | `jyoka/app` |
| [triggers.md](triggers.md) | 22〜26、110 | `jyoka/app`、`jyoka/web` |
| [task-format.md](task-format.md) | 322 | `https://github.com/jyoka/app/pull/41` |
| [architecture/lld.md](architecture/lld.md) | 760 | `jyoka/x` |

テストの偽物の GitHub も `jyoka/app` を使う(`tests/test_task.py` に 234 か所)。画像を撮るカードでは、写る名前を `you/notes-app` のような一般の名前にする。
ほかに、コードのコメントとテスト(`bin/task_hub.py`、`claude/task-board/`、`kiro/board-extension/test/`、`tests/`)にも `aica` や `jyoka/tasks` が出る。画面と README には出ない。

## 次のカードへの申し送り

- 画像を撮るカード: 済み(2026-10-29)。`python3 tests/media.py` が 4 節の例のカードを動かして撮り、`assets/media/` に置く。
  何をどこに使うかと撮り直し方は [media.md](media.md)
- README の絵のカード: バナーを README の一番上に置き(6 節の `<picture>`)、「しくみ」に分解の絵を置く。README の構成が変わるので、
  [CONTRIBUTING.md の「README の構成」](../CONTRIBUTING.md#readme-の構成)と `tests/test_brand.py` も直す
- LP のカード: 1 文を見出し、フッター、`llms.txt` で同じ文のまま使う。機能のカード 8 枚(3 節)、分解の絵(4 節)、`tokens.css` を使う。
  外から読み込まない、`prefers-reduced-motion` で止まる、スマホの幅で崩れないを、テストで確かめる
