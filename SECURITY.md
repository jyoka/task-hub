# セキュリティ

## 脆弱性の報告

脆弱性は、公開の Issue や Discussions に書かないでください。GitHub の private vulnerability reporting で、
非公開で知らせてください。

1. [Security の Advisories](https://github.com/jyoka/task-hub/security/advisories/new) を開く
   (リポジトリの **Security** タブ → **Report a vulnerability**)
2. 次を書く
   - 何が起きるか、どんな影響があるか
   - 再現の手順(`task --version` の版と OS も)
   - 分かっていれば、原因の場所(`bin/task` の関数名など)

報告の中身は、報告した人と管理者にだけ見えます。直し終えるまで公開しません。直したら、報告した人と相談して
advisory を公開します。

## 対象

最新の `main` だけを直します。古い版を使っているときは、`git -C ~/.local/lib/task-hub pull --ff-only` で更新して
から再現するか確かめてください。

task-hub はエージェントにファイルの編集とコマンドの実行を任せ、`[env]` で秘密情報のファイルを worktree にコピー
します。次のようなものは脆弱性として扱います。

- Issue の本文やコメントなど、外から書けるものから、意図しないコマンドが動く
- `[env]` のファイルや、`gh` のトークンなどの秘密情報が、PR、コメント、ログなどに漏れる
- worktree の外のファイルが書き換わる(エージェント自身の権限の設定によるものは除く)

エージェントそのもの(Claude Code、Codex、Pi、Kiro など)の脆弱性は、それぞれの提供元に報告してください。
