# オートパイロット(人の 2 つの判断を task-hub がする)

ふだん人がするのは 2 つです。カードを Ready に移す(始めてよいか)と、PR をマージする(入れてよいか)です。
`[autopilot]` にリポジトリを書くと、そのリポジトリのカードについて、task-hub が 2 つとも代わりにします。

| 人の判断 | オートパイロットでは |
|---|---|
| Backlog のカードを Ready に移す | 待ち先(Blocked by)がすべて終わったら、`task watch` が Ready に移し、同じ確認で始める |
| PR をマージする | 実行が In review で終わり、自動レビュー(reviewer)の判定が `pass` なら、マージキューに入れる。キューが base に追いつかせ、チェックを待ってマージする |

Blocked になったカード、自動レビューが通らなかったカード、PR のない調べもの(research)のカードは、今までどおり
あなたを待ちます。あなたは通知と `task events`、毎朝のまとめで、あとから何が起きたかを読みます。

## 設定

`~/.config/task-hub/config.ini` に書きます。`[autopilot]` がなければ、今までと何も変わりません。

```ini
[autopilot]
repos = jyoka/aica            ; カンマ区切り。owner/name。大文字と小文字は区別しない

[merge]
queue = on                    ; 必須。マージはマージキューを通す

[runner]
reviewer = agent              ; 必須。自動レビューが pass のものだけをマージする
```

- `repos` を書いたのに `[merge] queue = on` か `[runner] reviewer` がないと、`task` と `task watch` は何もせずに
  `error:` で止まります。レビューなしでマージしないためです
- `task watch` と `task` の確認のたびに動きます(1 分に 1 回)。GitHub への問い合わせは増えません。ボードの読み取りと
  `events.jsonl` だけで決めます

## 1 枚のカードに 1 回

| する事 | 条件 | 1 回の決め方 |
|---|---|---|
| Ready に移す | Backlog にある、Target repo が `repos` にある、待ち先がない、動いていない、Goal に `Autopilot: off` の行がない | そのカードに `autopilot`(`action: ready`)の出来事がまだない |
| マージキューに入れる | In review にある、Target repo が `repos` にある、最後の In review の出来事の判定が `pass` で PR がある、動いていない、Goal に `Autopilot: off` の行がない | その In review のあとに `queued` の出来事がまだない |

- Ready にするのはカードごとに 1 回だけです。あなたがカードを Backlog に戻すと、オートパイロットはもう動かしません
  (止めておきたいカードは Backlog に戻します)
- キューに入れるのはレビューごとに 1 回だけです。`task merge <番号> --cancel` でキューから外したカードは、もう入れません。
  次の実行でまたレビューが `pass` になれば、もう一度入れます
- `[triggers]` やスマートフォン(`task intake`)で作ったカードも、Backlog に入れば同じに扱います

## カードごとに外す(`Autopilot: off`)

Goal に次の 1 行を書くと、そのカードは Ready に移さず、PR もマージキューに入れません。引き継ぎのメモ、PRD、
人がする手順(本番のデプロイ、アカウントの設定)のカードに書きます。

```
Autopilot: off
```

行の頭と終わりの空白、大文字と小文字は区別しません。このカードは、いつもどおり Ready に移すか `task start` で始め、
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
