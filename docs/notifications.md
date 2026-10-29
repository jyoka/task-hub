# Blocked と In review をすぐ知る方法(調査)

2026-10-26 にタスク 251 で調べた結果です。カードが Blocked や In review になったとき、席にいない人へ
すぐ知らせる方法を比べました。外へ送る設定は、まだ何も変えていません。設定は人が確かめてからします。

## 結論

- **すぐ使えるのは `[notify] ntfy` です。** task-hub にもう入っていて、`config.ini` に 1 行書けば、
  Blocked と In review がスマートフォンに届きます。今のこのマシンの設定には `[notify]` がなく、ntfy は使っていません
- このマシンの通知(macOS の通知)は、既定で出ています。ただし Mac の前にいないと見えません。
  10/26 の 23:11 と 23:35 の Blocked に翌日まで気づかなかったのは、このためと考えられます(推測)
- GitHub の通知メールは、条件つきで使えます。task-hub は利用者自身の `gh` で書くので、普段は通知が来ません
- GitHub の Project の Status の変化は、利用者のボード(`you/2` のような個人の Project)では、どの方法でも外へ出せません

## 方法ごとの結果

| 方法 | 使えるか | 理由 |
|---|---|---|
| `[notify] ntfy`(ntfy.sh のトピック) | 使える(設定だけ) | 出来事を書く `task _run` 自身がその場で送る。見張りのプロセスも LLM も要らない。Blocked は優先度 4 |
| このマシンの通知(herdr、macOS) | 使える(既定で出ている) | Mac の前にいるときだけ見える。夜や外出中は届かない |
| GitHub の通知メール(既定) | 使えない | task-hub のコメント、PR、カードの移動は、どれも利用者自身のアカウントの操作。GitHub は自分の操作を通知しない |
| GitHub の通知メール(「Your own updates」を入れる) | 条件つき | 自分の操作もメールで来る。task-hub のレポートのコメント(Blocked も In review も)は届くはず。ただし手で書いたコメントもすべて来る。実際に届くかは未確認 |
| GitHub の通知の受信箱、モバイルアプリ | 使えない | 自分の操作は入らない(メールの「Your own updates」にあたる設定が見当たらない) |
| GitHub Actions(`projects_v2_item`) | 使えない | Project の webhook の出来事は、組織の Project にしかない。利用者のボードは個人の Project。Actions のトリガーにもない |
| GitHub Actions(`issue_comment`) | 使えるが勧めない | Issue リポジトリ(`you/tasks`)のレポートのコメントで動かせる。ただし送り先の鍵を Secrets に置く必要があり、結局 ntfy などに送るので二重になる |
| `/chief`(`task events --next` を Monitor で待つ) | 条件つき | すぐ知れるが、Claude Code の会話を開いておく必要があり、出来事ごとにトークンを使う |
| マネージャーの毎日 21:00 の確認(今のやり方) | 遅い | 最大で 1 日近く遅れる |

## 勧める設定(人が確かめてから)

```ini
[notify]
ntfy = https://ntfy.sh/<推測されにくいトピック名>
events = In review, Blocked, replan, slow, over budget
```

- スマートフォンに ntfy のアプリを入れ、同じトピックを購読します
- ntfy.sh は無料の範囲で、1 日に送れる数が 250 までです(ntfy の文書の Limitations)。既定の `events` のまま送ると、
  多い日に超えます。このマシンでは 2026-10-25 に、既定の出来事が 264 件ありました。Blocked と In review だけなら
  81 件でした
- `events` はこのマシンの通知にも効きます。`Done`、`update`、`conflict`、`autopilot` を外すと、それらは Mac にも出なくなります
- トピックの名前を知っている人は誰でも読めます。推測されにくい名前にするか、`ntfy_token` で守ります
  ([operations.md の「スマートフォンに届ける(ntfy)」](operations.md#スマートフォンに届けるntfy))
- 送るのは見出し(`#12 Blocked: <タイトル>`)と要点です。Goal やコードは送りません。要点には Blocked の理由と
  レビューの指摘が入るので、外に出してよい内容かは人が決めます

## 確かめたこと

- task-hub のコード: `notify` と `ntfy_post`(`bin/task`)。出来事を書く `emit` が、その場で通知と ntfy の送信を
  切り離して起動する
- このマシンの `config.ini`: `[notify]` の節がない。既定の `events` で、ntfy は空(送らない)
- このマシンの `events.jsonl`: 2026-09-26 から。Blocked と In review の多い日の件数は上のとおり
- GitHub の文書「Configuring notifications」: 既定のメールの設定に「Your own updates」がある。自分が開いた、
  コメントした、閉じた Issue や PR の更新をメールで受け取るかを選べる
- GitHub の文書「Webhook events and payloads」: `projects_v2_item` の Availability は `organization` だけ
- GitHub の文書「Events that trigger workflows」: Project のトリガーはない。`issue_comment` はある
- ntfy の文書「Publishing」: ntfy.sh の 1 日の上限は 250 件。メッセージは既定で 12 時間サーバーに残る

## 確かめていないこと

- 「Your own updates」を入れたとき、task-hub のコメントが実際にメールで届くか。設定を変える必要があるので試していません
- ntfy で実際にスマートフォンに届くか。外へ送る設定になるので試していません(送る処理そのものはテストで確かめています)
