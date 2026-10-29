# オートパイロット(人の 2 つの判断を task-hub がする)

ふだん人がするのは 2 つです。カードを Ready に移す(始めてよいか)と、PR をマージする(入れてよいか)です。
`[autopilot]` にリポジトリを書くと、そのリポジトリのカードについて、task-hub が 2 つとも代わりにします。

| 人の判断 | オートパイロットでは |
|---|---|
| Backlog のカードを Ready に移す | 待ち先(Blocked by)がすべて終わったら、`task watch` が Ready に移し、同じ確認で始める |
| PR をマージする | 実行が In review で終わり、自動レビュー(reviewer)の判定が `pass` なら、マージキューに入れる。キューが base に追いつかせ、チェックを待ってマージする |

指摘が minor(`Known issues`)だけのレビューも `pass` に数えます。reviewer の判定が `needs changes` でも、
`Please fix` が空で `Known issues` だけなら `pass` として記録し、マージします。minor の指摘は PR の本文の
「Known issues」に残るので、マージのあとで読みます
([task-format.md の「自動レビューの差し戻し」](task-format.md#自動レビューの差し戻し))。

Blocked になったカード、自動レビューが通らなかったカード、PR のない調べもの(research)のカード、一度でも
Backlog から出たカードは、今までどおりあなたを待ちます。あなたは通知と `task events`、毎朝のまとめで、あとから何が起きたかを読みます。

## 設定

`~/.config/task-hub/config.ini` に書きます。`[autopilot]` がなければ、今までと何も変わりません。

```ini
[autopilot]
repos = you/app               ; カンマ区切り。owner/name。大文字と小文字は区別しない

[merge]
queue = on                    ; 必須。マージはマージキューを通す

[runner]
reviewer = agent              ; 必須。自動レビューが pass(minor だけを含む)のものだけをマージする
```

- `repos` を書いたのに `[merge] queue = on` か `[runner] reviewer` がないと、`task` と `task watch` は何もせずに
  `error:` で止まります。レビューなしでマージしないためです
- `task watch` と `task` の確認のたびに動きます(1 分に 1 回)。決めるのはボードの読み取りと `events.jsonl` です。
  GitHub への問い合わせが増えるのは、キューに入れる前に PR を 1 回読むとき(`gh pr view`、レビューごとに 1 回)だけです

### 入れたときの、今の Backlog のカード

`repos` を書いた次の確認で、そのリポジトリの Backlog のカードのうち、**一度も Backlog から出ていないものはすべて**
Ready に移ります(待ち先のあるものは、待ち先が終わってから)。引き継ぎのメモ、PRD、人がする手順のカードには、
書く前に Goal に `Autopilot: off` の行を足します。前に動いたカード(Blocked のあとに Backlog に戻したものなど)は動かしません。

## 1 枚のカードに 1 回

| する事 | 条件 | 1 回の決め方 |
|---|---|---|
| Ready に移す | Backlog にある、Issue が開いている、Target repo が `repos` にある、待ち先がない、動いていない、Goal に `Autopilot: off` の行がない | 一度も Backlog から出ていない(このマシンに実行の記録がなく、`events.jsonl` に Backlog 以外の Status の出来事がない) |
| マージキューに入れる | In review にある、Target repo が `repos` にある、カードの最後の Status の出来事がその In review で、判定が `pass`(minor だけのレビューを含む)、PR がある、動いていない(競合を解く実行も)、Goal に `Autopilot: off` の行がない。PR がその実行の PR で、draft でなく、開いていて、先頭のコミットが実行の push したもののまま | その In review のあとに `queued` も `autopilot`(`merge`、`skip`)もない |

- Ready にするのは、一度も Backlog から出ていないカードだけです。前に動いたカード、あなたが `task start` したカード、
  Backlog に戻したカードは動かしません(止めておきたいカードは Backlog に戻します)
- キューに入れるのはレビューごとに 1 回だけです。`task merge <番号> --cancel` でキューから外したカードは、もう入れません。
  次の実行でまたレビューが `pass` になれば、もう一度入れます
- レビューのあとで PR が変わったとき(あなたの push、`[merge] prefix = on` の競合の解決)、draft にしたとき、
  別の PR になったときは、`autopilot`(`action: skip`)を 1 回出して、あなたに任せます。レビューした中身だけを
  マージするためです。`task merge <番号>` で入れられます
- カードを In review の列に手で動かしても、最後の実行が Blocked なら、そのときの古い `pass` ではマージしません
- `[triggers]` やスマートフォン(`task intake`)で作ったカードも、Backlog に入れば同じに扱います

## カードごとに外す(`Autopilot: off`)

Goal に次の 1 行を書くと、そのカードは Ready に移さず、PR もマージキューに入れません。引き継ぎのメモ、PRD、
人がする手順(本番のデプロイ、アカウントの設定)のカードに書きます。

```
Autopilot: off
```

行の頭と終わりの空白、大文字と小文字は区別しません。箇条書き(`- Autopilot: off`)、強調やコード
(`**Autopilot: off**`、`` `Autopilot: off` ``)、終わりの句点(`Autopilot: off.`)でも効きます。このカードは、いつもどおり Ready に移すか `task start` で始め、
PR はあなたがマージします(`task merge <番号>` も使えます)。

## チェックのないリポジトリ

マージキューは、PR のチェックが通ってからマージします。チェックが 1 つもないリポジトリ(GitHub Actions がない)では、
push から 2 分待ってもチェックが出なければ、待たずにマージします。ブランチの保護もなければ(GitHub の無料のプランの
private のリポジトリ)、GitHub はいつでもマージを許します。**このときマージを止めるのは、自動レビューの判定だけです。**

- reviewer は、実装とは別の新しいコンテキストで、受け入れ条件とテストを確かめます(`worker/REVIEW.md`)。テストを
  動かしたかどうかは reviewer しだいで、CI のように必ず動くものではありません
- 守りを足すなら、リポジトリに GitHub Actions のテストを足します。キューはそのチェックが通るまでマージしません

## 出来事と通知

| `event` | `action` | いつ | `reason` |
|---|---|---|---|
| `autopilot` | `ready` | Ready に移した | どの設定で |
| `autopilot` | `merge` | マージキューに入れた | レビューが通ったこと、キューの何番目か |
| `autopilot` | `skip` | レビューは通ったが、入れずにあなたに任せた | PR が変わった、draft、開いていない、別の PR |

そのあとはいつもの出来事が続きます(`Ready`、`In progress`、`In review`、`queued`、`merged`、`Done`)。
`autopilot` は通知の既定(`[notify] events`)に入っているので、OS の通知と、ntfy を設定していればスマートフォンにも出ます。
`[notify] events` を自分で書いているときは、`autopilot` を足します。

## 安全のために

- `repos` に書くのは、Issue を書ける人と、そのリポジトリでエージェントがすることを信頼できるリポジトリだけにします。
  `[triggers] issues` のカードは、Issue の本文をエージェントが読みます。オートパイロットでは、その本文を人が読む前に
  始まります([triggers.md](triggers.md#安全のために))
- Mac と Windows では、エージェントはあなたの権限で動きます([agents.md](agents.md#安全性))。人の見ていない実行が
  増えるので、Goal の `Rules`([task-format.md](task-format.md#rules-タスクごとの決まり))で、してはいけないこと
  (`git push --force`、本番へのデプロイなど)を書いておきます。Linux では `[sandbox] mode = user`([sandbox.md](sandbox.md))も使えます
- 止めるときは、`[autopilot]` の `repos` を消すか空にします。次の確認から効きます。動いている実行とキューの PR は、
  そのまま進みます(キューから外すのは `task merge <番号> --cancel`)
