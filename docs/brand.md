# 伝え方: 1 文、3 本の柱、機能の文、見た目、バナー

task-hub を外に伝えるときの土台です。README の絵、画像、LP を作るカードは、まずこれを読みます。

- 状態: 1 文を言い直し、3 本の柱、人ごとの 1 行を足し、機能のカードを柱の順に組み直した(2026-10-29)
- 置き場所: この文書と [`assets/brand/`](../assets/brand/)(`tokens.css`、`banner-dark.svg`、`banner-light.svg`)
- お手本は tuios の作りと書き方。文、絵、ロゴは写さない
- 例のデータは、どれも架空。本物のボード、Issue、リポジトリの名前は使わない(7 節)

## 結論

- 1 文は「**AI に任せて、離れていい。確かめてから届くから。**」。
  英語は「**Hand work to AI agents and walk away. Nothing reaches you unchecked.**」
- この 1 文を、README の太字、バナー、LP の見出し、GitHub の About で、同じ文のまま使う。変えるときは全部を一度に変える
- 軸は「何が良くなるか」。GitHub は手段なので、1 文と見出しには出さず、説明の中に下げる
- 伝えることは 3 本の柱(安心、軽さ、信頼)にまとめる。どの柱にも、支える機能と、確かめられる事実を付ける(2 節)
- 機能は、名詞の見出しと 2 行の説明のカード 8 枚で、柱の順に伝える(3 節)。形容詞を使わず、コマンド、設定、数で書く
- 「確かめてから届く」は、自動レビューが既定で入ることが前提。外した人には当てはまらない(1 節の「前提」)
- 分解の絵は、1 枚のカードの一生を 8 つの層に分ける。層の色は「誰がするか」(あなた、task-hub のコード、エージェント)を表す(4 節)
- 見た目は [`assets/brand/tokens.css`](../assets/brand/tokens.css) の CSS の変数で決める。意味の色は、どれもコントラスト比 4.5 以上(5 節)
- README と docs に残っていた運営者の私的な名前は、一般の言い方か架空の例に直した。`tests/test_brand.py` が、戻っていないかを確かめる(7 節)
- LP は https://jyoka.github.io/task-hub/ で公開した(2026-10-30 に決めた。7 節)

## 1. 1 文

task-hub を使うと何が良くなるかを、1 文で言い切る。

### 決めた文(2026-10-29)

| 日本語 | 英語 |
|---|---|
| **AI に任せて、離れていい。確かめてから届くから。** | **Hand work to AI agents and walk away. Nothing reaches you unchecked.** |

運営者と一緒に、task-hub の本質を言い直して決めた。

### 続く 2〜3 行

1 文のすぐ下に置く。README の上の部分と LP の見出しの下の説明は、この文をもとに書く。

| 日本語 | 英語 |
|---|---|
| 頼みたいことを Goal に書いて渡すだけ。 | Write what you want as a Goal and hand it over. |
| 手元の AI エージェントが作る。作っていない新しい目が Goal と突き合わせて確かめ、直してから届ける。 | An AI agent on your machine builds it. A fresh pair of eyes that did not build it checks the work against the Goal, and it is fixed before it reaches you. |
| あなたが決めるのは「何をやるか」と「出してよいか」の 2 つだけ。 | You decide only two things: what to do, and whether it may ship. |
| 頼んだことから決めたことまで、全部があとからたどれる。 | Everything, from what you asked to what you decided, can be traced later. |

- 「作っていない新しい目」は、実装を見ていない新しい文脈のレビュー([agents.md](agents.md#自動レビュー))。
  既定では、実装と同じエージェントを新しい文脈で動かす。別のモデルとは限らないので、「別の AI」とは書かない
- 「何をやるか」はカードを Ready に移すこと、「出してよいか」は PR をマージすること。README の上の 2 つの箇条書きに当たる
- 「全部」は、Issue の Goal、レポート、レビューの判定、PR、ボードの列、`task events` と `task stats` の記録

### 旧い案と選んだ理由

| 案 | 日本語 | 英語 | 判断 |
|---|---|---|---|
| 新 | AI に任せて、離れていい。確かめてから届くから。 | Hand work to AI agents and walk away. Nothing reaches you unchecked. | **採る**(2026-10-29) |
| 旧 A | Ready に移した GitHub Project のカードを、手元のエージェントがレビュー済みの PR にする。 | Your local coding agents turn each GitHub Project card you move to Ready into a reviewed PR. | やめる。タスク 397 で決めたが、操作の説明で、何が良くなるかを言っていない |
| 旧 B | 決めるのは Ready とマージの 2 つだけで、その間は手元のエージェントが進める。 | You decide two things, Ready and merge, and your local coding agents do the rest. | 見送ったまま。「2 つだけ決める」は続く行に残した |
| 旧 C | GitHub Project のボードを、手元のコーディングエージェントの仕事の列にする。 | Turn a GitHub Project board into the work queue for the coding agents on your machine. | 見送ったまま。道具の説明で、何が出てくるかも、何が良くなるかも言わない |

新しい文を選んだ理由:

- 旧 A は操作の説明だった。GitHub は手段で、軸ではない。1 文から GitHub、Project、PR を外し、続く行と機能の説明に下げた
- 速さだけでなく、質が上がることを言う。「確かめてから届く」は、作った AI と別の目が確かめてから人に届く、という質の約束
- 届けたい人は 3 つ。1 人で多くのエージェントを回す開発者、チームのリーダー、エンジニアでない人。
  旧 A の「GitHub Project のカード」「PR」は、エンジニアでない人に届かない
- 解く困りごとは 3 つ。目を離すと変なものができる、セッションの見張りに張り付く、何をどこまで頼んだか分からなくなる。
  「離れていい」が 2 つ目に、「確かめてから届く」が 1 つ目に答える。3 つ目は続く行の「全部があとからたどれる」が答える
- 使った人に感じてほしいことは 3 つ。「任せても大丈夫」という安心、「自分は判断に集中できる」という軽さ、
  「全部たどれる」という信頼。これを 2 節の 3 本の柱にした
- 数字の裏づけがある。自動レビューの最初の判定で、約 3 回に 1 回が「直す点あり」で差し戻された(2 節の安心の柱)
- 長さ: 日本語で 24 字(空白を除く)。2 つの短い文で、目安の 40 字に収まる

### 前提: 自動レビューが既定で入る

「確かめてから届く」と言えるのは、自動レビューが既定で入るから。`[runner] reviewer` を省略しても、PR の前に
新しい文脈のレビューが動く([design.md](design.md) の決定事項 38、[usage.md](usage.md#設定))。

`[runner] reviewer = off`(または空)と書いて自動レビューを外した人には、「確かめてから届く」は当てはまらない。

### 今の文との比べ

| 場所 | 前の文 | このカードで |
|---|---|---|
| README の太字、バナー、LP、`llms.txt` | 旧 A | 新しい文に直した |
| README の上の 2〜3 行 | 「You make two decisions」と、task-hub がする作業の並び | 続く 2〜3 行をもとに直した。決める 2 つの箇条書きは残した |
| GitHub の About | Move a GitHub Project card to Ready; your local coding agent (Claude Code, Codex, Pi, Kiro) implements it and opens a PR | 運営者が変える(下) |

GitHub の About は運営者が変える。案は新しい文の英語をそのまま使う:
`Hand work to AI agents and walk away. Nothing reaches you unchecked.`
エージェントの名前と GitHub Project で動くことは、README の上の部分と About の Topics に任せる。

### 使う場所

| 場所 | 使う文 |
|---|---|
| `README.md` の太字 | 英語 |
| `README.ja.md` の太字 | 日本語 |
| バナー(6 節) | 両方 |
| GitHub の About | 英語(運営者が変える) |
| LP の見出し、フッター、`llms.txt`([`site/`](../site/)) | 日本語と英語 |

[`tests/test_brand.py`](../tests/test_brand.py) が、2 つの README の太字、この文書、2 枚のバナーの文が同じかを確かめる。
LP の見出し、フッター、`site/llms.txt` は [`tests/test_site.py`](../tests/test_site.py) が確かめる。

### 英語の言葉

英語で書くときは、次の語を使う。README と同じ語にしている。

| 日本語 | 英語 |
|---|---|
| カード | card |
| タスク | task |
| ボード | board |
| 手元のエージェント | local coding agent、AI agent on your machine |
| 新しい文脈のレビュー、自動レビュー | fresh-context review、automated review |
| 確かめる、届く | check、reach you |
| 受け入れ条件 | acceptance criterion |
| 差し戻し | send back |
| マージの順番待ち | merge queue |
| 止まった理由の仕分け | sorting out why a task stopped |
| 前後関係 | dependency |
| 安心、軽さ、信頼(3 本の柱) | peace of mind、focus、trust |

## 2. 誰のためか、3 本の柱

| | 日本語 | English |
|---|---|---|
| 誰のためか | 1 人で多くのエージェントを回す開発者、チームのリーダー、エンジニアでない人。エージェントは Claude Code、Codex、Pi、Kiro など、手元で動く CLI。 | Developers who run many agents alone, team leads, and people who are not engineers. The agents are CLIs on your own machine: Claude Code, Codex, Pi, Kiro, and others. |
| 何が楽になるか | 頼むことと出すことを決めるだけ。その間の実装、テスト、新しい文脈のレビュー、直し、PR、止まった理由の仕分けは、task-hub とエージェントが進める。 | You decide what to do and whether it may ship. task-hub and your agents do the rest: implement, test, review in a fresh context, fix, open the PR, and sort out why a task stopped. |
| 何が分かるか | どのカードも、Issue に Goal、レポート、レビューの判定が残り、ボードの列で今どこにいるかが分かる。`[autopilot]` を書いたリポジトリでは、自動レビュー(`review_mode = goldfish` なら 2 つの視点)に合格した PR が、マージキューでマージまで進む。 | Each card leaves its Goal, report, and review verdict on the Issue, and its column shows where it is. For repositories under `[autopilot]`, a PR that passes the automated review (two viewpoints with `review_mode = goldfish`) goes through the merge queue to the merge. |

### 3 本の柱

使った人に感じてほしいことを 3 本の柱にした。機能のカード(3 節)は、この順に並べる。

| 柱 | 感じてほしいこと | 答える困りごと | 支える機能(3 節のカード) |
|---|---|---|---|
| 安心 / Peace of mind | 「任せても大丈夫」 | 目を離すと変なものができる | 届ける前の確かめ、Goal の確認、Blocked の仕分け |
| 軽さ / Focus | 「自分は判断に集中できる」 | セッションの見張りに張り付く | 止まった後の再開、通知、マージキュー |
| 信頼 / Trust | 「全部たどれる」 | 何をどこまで頼んだか分からなくなる | カードごとの作業場所、コードが残す記録 |

英語の「Focus」は「軽さ」の直訳ではない。軽さの中身(判断に集中できる)を 1 語にした。

#### 確かめられる事実

数字は、運営者のマシンで `task stats` を動かして取り直した(2026-10-29)。期間は 2026-09-26 から 2026-10-29 までの
427 回の実行。出どころは、task-hub が実行ごとに 1 行ずつ書く記録(`~/.local/state/task-hub/metrics.jsonl`)。
背景の 426 回、398 回は、取り直すまでに実行が 1 回増えた分だけ違う。ほかの人のマシンの数ではない。

| 柱 | 事実 | 出どころ |
|---|---|---|
| 安心 | 自動レビューを受けた 399 回のうち、最初の判定で 137 回(約 3 回に 1 回)が `needs changes`(直す点あり)で差し戻された | `task stats` の `reviews`、`first_verdicts` |
| 安心 | 差し戻された 137 回のうち、67 回は直した後に `pass` になった | `task stats` の `reviews` |
| 安心 | 自動レビューに通らなかった 74 回は、出来上がりとして届けずに Blocked で止めた | `task stats` の `blocked_by` の `review` |
| 軽さ | 止まった 106 回は、どれも理由つきで人に戻った(自動レビュー 74、エージェントの質問 13、レポートなし 9、開始の失敗 6、終わりの処理の失敗 4) | `task stats` の `outcomes`、`blocked_by` |
| 軽さ | 人が決めるのは Ready とマージの 2 つ。カードは最大 5 つが並んで動き、`task watch` が 1 分ごとにボードを読む | [usage.md](usage.md)、README の「タスクの一生」 |
| 信頼 | 427 回のどれも、結果が記録に残る。レビューを受けた回は判定、止まった回は理由も残り、`task stats` で数え直せる。この節の数字もそこから取った | `task stats` |
| 信頼 | git、PR、Issue のコメントは、エージェントではなく task-hub のコードが行う。LLM を使うのは、実装、レビュー、止まった理由の仕分けの 3 か所だけ | README の「しくみ」、[architecture/hld.md](architecture/hld.md) |

427 回のうち 28 回は、レビューの判定がない。エージェントの質問 13、開始の失敗 6、レポートなし 9 の計 28 回と数は合い、
どれもレビューの前に止まる種類なので、届かずに止まった回だと推測する。1 回ずつは確かめていない。

数字を変えるときは、`task stats` を動かし直し、期間と回数をこの表と一緒に直す。推測で数を足さない。

### 人ごとの 1 行

| 人 | 日本語 | English |
|---|---|---|
| 1 人で多くのエージェントを回す人 | 5 つまで並べて任せ、見張らずに、確かめ済みのものだけを見る。 | Run up to 5 tasks at once without watching them, and look only at work that has been checked. |
| チームのリーダー | 誰が何を頼み、何を確かめ、何を決めたかが、カードと Issue に残る。 | Who asked for what, what was checked, and what was decided stay on each card and its Issue. |
| エンジニアでない人 | やりたいことを言葉で書けば、確かめ済みの形で届く。決めるのは、始めるかと出すかだけ。 | Describe what you want in words, and it comes back checked. You only decide whether to start and whether to ship. |

- チームのリーダーには、`task share` で、選んだカードをチームの Issue と Project に写せることを添える([usage.md](usage.md#チームのボードに出すtask-share))
- エンジニアでない人には、Kiro IDE ならターミナルなしで始められることを添える([kiro-quickstart.md](kiro-quickstart.md))

## 3. 機能のカード 8 枚

書き方の決まり:

- 見出しは名詞 2〜3 語。形容詞を使わない。GitHub、PR などの言葉は見出しに使わず、説明の中に書く
- 説明は 2 行。1 行目は何ができるか、2 行目は具体(コマンド、設定、数)
- 並びは 2 節の 3 本の柱の順(安心、軽さ、信頼)。表の最後の列が柱
- カードの絵は task-hub の本物の画面(テストの偽物の GitHub で作った架空のボード)にし、押すと「詳しく」の docs に飛ぶ

| # | 見出し | 説明(日本語) | Heading | Description | 詳しく | 柱 |
|---|---|---|---|---|---|---|
| 1 | 届ける前の確かめ | 実装を見ていない新しい文脈のエージェントが、受け入れ条件を 1 つずつ確かめ、足りなければ差し戻す。<br>既定で入り、PR を開く前に動く。差し戻しは既定で 2 回まで。`review_mode = goldfish` では、レポートを読まない 2 つの視点が見る。 | Check before delivery | An agent in a fresh context, one that did not build the work, checks each acceptance criterion and sends the work back if one fails.<br>On by default, before the PR opens. 2 send-backs at most by default. With `review_mode = goldfish`, two viewpoints that skip the report check it. | [agents.md](agents.md#自動レビュー) | 安心 |
| 2 | Goal の確認 | `task check <番号>` で、Goal とコードだけを知るエージェントが GO / NO-GO を出す。<br>NO-GO には Goal に足す文言が付く。`readiness = require` なら、GO のないカードは始まらない。 | Goal check | `task check <id>` has agents that know only the Goal and the code say GO or NO-GO.<br>A NO-GO comes with wording to add. With `readiness = require`, a card without a GO does not start. | [task-format.md](task-format.md#ready-の前の確かめtask-check) | 安心 |
| 3 | Blocked の仕分け | 確かめに通らない実行は、出来上がりとして届けず、理由を付けて止める。理由はボードと Issue に出る。<br>`replanner` を入れると、エージェントが理由を仕分けて Issue にコメントする。Goal に答えを足して Ready に戻すと、同じ PR で続く。 | Blocked triage | A run that fails the check stops with its reason instead of reaching you. The reason shows on the board and the Issue.<br>With `replanner`, an agent sorts out why and comments on the Issue. Add the answer to the Goal, move the card to Ready, and the same PR continues. | [agents.md](agents.md#blocked-の仕分けreplanner) | 安心 |
| 4 | 止まった後の再開 | クラッシュや再起動で止まった実行を、止まった所から 1 回だけ再開する。<br>利用の上限で止まったら、戻る時刻を書いて待ち、戻ったら同じ所から続ける。 | Stop recovery | A run that stops on a crash or a restart resumes once, from where it stopped.<br>A run that hits the usage limit waits for the reset time, then goes on from the same place. | [operations.md](operations.md#利用の上限で止まった) | 軽さ |
| 5 | 通知 | 見張らなくても、In review、Blocked、長い実行、予算超えを知らせる。<br>OS の通知と ntfy(スマートフォン)に届く。知らせるかどうかはコードが決め、LLM は使わない。 | Alerts | You need not watch: In review, Blocked, long runs, and runs over budget come to you.<br>They show as OS notifications and on ntfy (your phone). Code decides when to notify; no LLM is used. | [operations.md](operations.md#通知llm-なし) | 軽さ |
| 6 | マージキュー | `task merge` で承認した PR を、base に追いつかせ、チェックを待ってマージする。<br>衝突はエージェントが直す。1 つのリポジトリで 1 度に 1 本。 | Merge queue | `task merge` approves a PR; the queue brings it up to date with its base, waits for its checks, and merges it.<br>An agent fixes conflicts. One PR per repository at a time. | [operations.md](operations.md#マージキュー) | 軽さ |
| 7 | カードごとの作業場所 | 1 枚のカードに、1 つのブランチ、1 つの worktree、1 つの PR。頼んだことと届いたものが 1 対 1 で並ぶ。<br>最大 5 つを並べて動かし、ブランチは `task/<番号>`。 | A workspace per card | Each card gets one branch, one worktree, and one PR, so what you asked for and what came back line up one to one.<br>Up to 5 run at the same time, on branches named `task/<id>`. | [usage.md](usage.md#見え方と手元に残るもの) | 信頼 |
| 8 | コードが残す記録 | git、PR、Issue のコメントは、エージェントではなく task-hub のコードが行う。どのエージェント CLI でも同じ形で残る。<br>起動ごとのトークンと費用も、エージェント CLI の記録から読む(`task stats`)。 | Records kept by code | task-hub, not the agent, does git, the PR, and the Issue comments in code, so every agent CLI leaves the same kind of record.<br>Tokens and cost per launch come from the agent CLI's own records (`task stats`). | [task-format.md](task-format.md#task-hub-のレポートコメント) | 信頼 |

前の並び(2026-10-29 の LP のカード)からの変え方:

- 「1 タスク 1 PR」は「カードごとの作業場所」に、「PR の前のレビュー」は「届ける前の確かめ」に変えた。見出しから PR を外した
- 「エージェントの選択」は「コードが残す記録」に変え、「通知と費用」の費用の行をこちらに移した。どのエージェントでも記録が同じ形になることが、信頼の柱を支えるため
- 「通知と費用」は「通知」にした。見張らなくてよいことが、軽さの柱を支えるため
- 「マージキュー」の見出しは残した。GitHub や PR の名前ではなく、手元の git でも使う言葉なので

README の「特長」は、上の 8 枚に合わせた。画面の 4 枚(届ける前の確かめ、Blocked の仕分け、ボードを横に、カードごとの作業場所)は
画像付きの 2 列の表にし、柱の順に並べた。残りは 1 行ずつの箇条書きにした。

## 4. 分解の絵の台本

1 枚のカードの一生を、層に分けて見せる絵。LP の真ん中に置く(作るのは LP のカード)。README では、一番上のバナーの右の 8 層が、
この絵の止まった短い形になる。README の「しくみ」は Mermaid の図のままにした。

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
- 1 文を言い直したとき(2026-10-29)、左の文を新しい 1 文に変え、日本語を 2 行、英語を 2 行にした。右の 8 層と凡例は変えていない

README の一番上に、ダークとライトを `<picture>` で出し分けて置いた(2026-10-29)。README の alt は、絵の中身(1 文と 8 層)を書いた長い文にした。

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/banner-dark.svg">
  <img alt="task-hub: Hand work to AI agents and walk away. Nothing reaches you unchecked." src="assets/brand/banner-light.svg">
</picture>
```

## 7. 公開の記録

LP([`site/`](../site/))を https://jyoka.github.io/task-hub/ で公開した(運営者が 2026-10-30 に決めた)。
GitHub Pages に、[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) が main への push で出す。
出し方、出し直し方、止め方は [site/README.md の「公開」](../site/README.md#公開)。

公開の前に、外向けの文に出ていた運営者の私的な名前を、一般の言い方か架空の例に直した(2026-10-29)。直したのは、README の 2 つ、
CONTRIBUTING.md、SECURITY.md、AGENTS.md と、docs/ の全部。手順や決まりは変えず、名前だけを直した。

| 種類 | 直し方 | 直したファイル |
|---|---|---|
| 運営者の本物のボード(Project の番号) | `you/2`、`you/3` か、「試験用の Project」「本番の Project」 | [notifications.md](notifications.md)、[release.md](release.md)、[review-2026-10-03.md](review-2026-10-03.md) |
| private のリポジトリ(Issue のリポジトリ、試験用のリポジトリ、仕事のリポジトリ) | `you/tasks`、`you/app`、`you/task-sandbox` | README の 2 つ、[setup.md](setup.md)、[operations.md](operations.md)、[autopilot.md](autopilot.md)、[issue-tracker.md](issue-tracker.md)、[task-format.md](task-format.md)、[release.md](release.md)、[architecture/designs/team-sync.md](architecture/designs/team-sync.md) |
| 本物の Issue と PR の番号、リンク | 根拠に引くだけの所は番号を外し、「あるカード」「運営者のボード」と書く。実験の記録で同じカードを何度も指す所は、ア、イ、ウ…と呼ぶ | [design.md](design.md)、[lessons.md](lessons.md)、[task-format.md](task-format.md)、[kiro-ide.md](kiro-ide.md)、[roadmap-statecharts.md](roadmap-statecharts.md)、[review-2026-10-03.md](review-2026-10-03.md)、[architecture/lld.md](architecture/lld.md)、[architecture/designs/autopilot-unblock.md](architecture/designs/autopilot-unblock.md) |
| 仕事の名前、カードの題、手元のパス | 「運営者の別のプロダクト」「本物に近い例」。題は何が起きたかが分かる一般の言い方。パスは `~/code/app/` | [setup.md](setup.md)、[operations.md](operations.md)、[design.md](design.md)、[lessons.md](lessons.md)、[architecture/designs/autopilot.md](architecture/designs/autopilot.md)、[architecture/designs/autopilot-unblock.md](architecture/designs/autopilot-unblock.md) |
| 運営者のアカウント名を使う架空の例 | `you/app`、`you/web` | [usage.md](usage.md)、[triggers.md](triggers.md)、[task-format.md](task-format.md)、[architecture/lld.md](architecture/lld.md) |

何があったかは残した。たとえば [lessons.md](lessons.md) の実験の表は、カードの番号と仕事の題を外し、不合格の理由、判定、
時間、トークンはそのままにした。

数えないもの:

- `jyoka/task-hub`: このリポジトリそのもの(public)。clone の URL、バッジ、Discussions
- `jyoka/workenv_setting`([sandbox.md](sandbox.md)): public のリポジトリ
- `you/tasks#12`、`#12`、`<you>/task-sandbox`、`<owner>`: 一般の言い方と架空の例
- 「タスク 252」のような、決定事項と教訓の出どころの番号: リポジトリの名前も題も持たないので残した。公開でも残すと、運営者が決めた

### 戻らないようにする確かめ

`tests/test_brand.py` の `test_the_public_docs_name_no_private_board_or_work` が、README の 2 つ、CONTRIBUTING.md、
SECURITY.md、AGENTS.md、docs/ の全部の `.md` に、上の種類の名前が戻っていないかを確かめる。探す名前は、テストの
`PRIVATE` にある。この文書には名前を書かない(書くと、この文書が名前を出すことになるため)。
LP([`site/`](../site/))は、`tests/test_site.py` が同じ確かめをする。

### 残した所: docs の外

画面と README には出ないので、直していない。LP にも出ない(`tests/test_site.py` が確かめる)。公開のときも直していない。

- `task watch` の設定の誤りのメッセージ(`bin/task_hub.py` の `[triggers]` の例)が、運営者のアカウント名を使う架空の
  リポジトリを出す。コマンドの出力なので、直すならテストと合わせて別のカードで直す
- コードのコメント(`bin/task_hub.py`、`claude/task-board/hooks/panel.ts`)と、テスト(`tests/`、`claude/task-board/`、
  `kiro/board-extension/test/`)に、本物の Issue と仕事のリポジトリの名前が出る
- テストの偽物の GitHub は、運営者のアカウント名を使う架空のリポジトリ(`tests/test_task.py`)。画像に写る名前は、
  画像を撮るカードが `you/notes-app` のような一般の名前にした([media.md](media.md))

## 次のカードへの申し送り

- 画像を撮るカード: 済み(2026-10-29)。`python3 tests/media.py` が 4 節の例のカードを動かして撮り、`assets/media/` に置く。
  何をどこに使うかと撮り直し方は [media.md](media.md)
- README の絵のカード: 済み(2026-10-29)。バナー、1 文の下の動く画像、「特長」の画面 4 枚の表を置き、
  [CONTRIBUTING.md の「README の構成」](../CONTRIBUTING.md#readme-の構成)と `tests/test_brand.py` を直した。
  分解の絵は README には置かず、LP に任せた(4 節)
- LP のカード: 済み(2026-10-29)。[`site/`](../site/) に置いた。開き方、確かめ方、GitHub Pages に出す手順は
  [site/README.md](../site/README.md)。`tests/test_site.py` が、1 文、機能のカード 8 枚と 8 つの層がこの文書と同じこと、外から読み込まないこと、
  `prefers-reduced-motion` で動かない作りを確かめる。スクロールの動きとスマホの幅は、手元の Chrome で確かめた
- 1 文の言い直しのカード: 済み(2026-10-29)。1 節の 1 文、2 節の 3 本の柱と人ごとの 1 行、3 節のカードの並びを決め、
  README、LP、`site/llms.txt`、バナーを合わせた
- LP の公開のカード: 済み(2026-10-30)。`.github/workflows/pages.yml` を足し、https://jyoka.github.io/task-hub/ に出すようにした。
  README の 2 つの上の部分に LP へのリンクを置いた。出し方と止め方は [site/README.md の「公開」](../site/README.md#公開)
