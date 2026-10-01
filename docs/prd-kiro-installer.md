# PRD: Kiro IDE 版 task-hub のかんたんセットアップ (2026-10-02)

## 1. 背景

- Kiro IDE 版 task-hub は main に入り、Kiro IDE 1.2.4 で一周を確かめました(dip-ka-jo/tasks#41〜#55、[kiro-ide.md](kiro-ide.md) の 8 章)。
- 今のセットアップは、ターミナルでのコマンドが 30 以上あります。対象は次の 4 つにまたがります。
  - 依存ツール: gh、Python、kiro-cli
  - GitHub の準備: タスク用リポジトリ、Project、欄、ワークフロー
  - `config.ini`
  - Kiro との連携: スキル、steering、フック、ワークフロー、設定
- これを **同僚に配ります**。相手はターミナルに慣れていない前提です。
- 仕事用の Mac は情シスの管理下にあります。**管理者権限が要る入れ方(Homebrew、`sudo`、pkg のインストーラ)は使えません。**

## 2. 目的

同僚が、Kiro IDE で task-hub のリポジトリを開き、チャットに「セットアップして」と言うだけで、最初のタスクを In review まで回せるようにします。

| # | 目的 | 今 |
|---|---|---|
| G1 | 1 つのコマンド(`kiro/install.sh`)が、足りないものを判定して入れる | 手で 30 以上のコマンド |
| G2 | 管理者権限を一切使わない。入れるものはすべてホームの下(`~/.local`、`~/.kiro`、`~/Library/LaunchAgents`) | Homebrew や pkg が前提の部分がある |
| G3 | 何度実行しても安全。途中で止まっても、もう一度実行すれば続きから進む | 手順の途中で失敗すると、どこまで済んだか分からない |
| G4 | 本人の操作が要るところ(ログインなど)では止まって、何をすればよいかを 1〜2 行で伝える | setup.md を読んで判断する |
| G5 | 終わったら「診断」が足りないものを一覧で出す。後からいつでも実行できる | なし |
| G6 | 1 人 1 ボード(タスク用リポジトリと GitHub Project)を自動で作る | 画面で手作業(Status の選択肢、テキスト欄 3 つ、ワークフロー) |

### 成功の基準

- task-hub を使ったことのない同僚が、**30 分以内に** 最初のタスクを In review まで進められる
- その間に管理者パスワードを 1 回も聞かれない
- 自分でターミナルにコマンドを打たない(Kiro のチャットが実行する)

## 3. やらないこと

- **別ブランチでの配布。** main に置き、配布する版はタグで示します(例: `kiro-v1`)。
- Homebrew、`sudo`、pkg のインストーラを使う入れ方。
- Kiro IDE 自体のインストール。情シスの配布に任せます。
- herdr のインストール。任意の部品で、なくても動きます。
- Windows と Linux への対応。

## 4. 使い方(同僚から見た流れ)

```
0. (前提) Kiro IDE と git が入っていて、dip-ka-jo/task-hub を読める GitHub アカウントがある
1. Kiro IDE の「Clone Repository」で task-hub を clone して開く(GitHub へのログインは IDE が案内する)
2. チャットに「セットアップして」と書く
   → リポジトリの steering(.kiro/steering/setup.md)に従い、Kiro が sh kiro/install.sh を実行する
3. インストーラが止まったところで、案内どおりにブラウザでログインする
   (gh の device flow、kiro-cli のログイン)
4. もう一度「続けて」と言う → インストーラが残りを進め、最後に診断を出す
5. Kiro を再起動し、新しいチャットで /task を試す
```

## 5. インストーラの段階

インストーラは段階ごとに「済んでいるか」を確かめ、済んでいなければ実行します(G3)。入れたものは
`~/.local/state/task-hub/install-manifest.json` に記録し、アンインストールに使います。

| 段階 | 内容 | 管理者権限なしで入れる方法 | 本人の操作 |
|---|---|---|---|
| 1. 前提の確認 | macOS、CPU の種類、git、ネットワーク(プロキシを含む) | 確認だけ。git がなければ情シスへの依頼文を出して止まる | — |
| 2. Python | `task` 本体は Python 3.10 以上が必要 | 既存の `python3` が 3.10 以上ならそれを使う。なければ **uv**(単体のバイナリ)を `~/.local/bin` に入れ、uv で Python を取る | — |
| 3. gh | GitHub CLI | GitHub Releases の macOS 用 zip を curl で取り、`checksums.txt` で確かめてから `~/.local/bin` に置く | — |
| 4. kiro-cli | worker の実行に使う | **要調査**(PBI 1)。今あるのは `/Applications/Kiro CLI.app` 版 | — |
| 5. task-hub 本体 | `~/.local/lib/task-hub` に clone し、`~/.local/bin/task` にリンクする。PATH を `~/.zprofile` に足す | git clone | — |
| 6. ログイン | `gh auth login`(`project` スコープ込み)と kiro-cli のログイン | — | **ブラウザで承認** |
| 7. ボード | `<user>/tasks`(private)と GitHub Project を作る。欄(Status の選択肢、Target repo / Agent / Base branch)と「Item closed」を用意する | gh と GraphQL。テンプレートの Project を `gh project copy` で写す案と、API で組み立てる案がある(PBI 1 で決める) | — |
| 8. 設定 | `~/.config/task-hub/config.ini` を書く(`[board]`、`[runner] agent = kiro`、`[check] kiro`、`[ide] open`) | ファイルを書くだけ | — |
| 9. Kiro との連携 | スキルとsteering はリンクで入れる。フックとワークフローは **コピー** で入れる(リンクでは Kiro が読まない、2026-10-02 に確認)。`kiroAgent.workflows.enabled` を有効にする | ファイルの操作と、Kiro の settings.json の書き換え | Kiro の再起動 |
| 10. 常駐(任意) | `task watch` を launchd で動かす。`KIRO_API_KEY` を使う場合はキーチェーンに入れる | `~/Library/LaunchAgents` と `security` コマンド。どちらもユーザー単位 | キーの貼り付け(使う場合) |
| 11. 診断 | 上の全段階を確かめ、足りないものを一覧で出す | — | — |

### 守ること

- **ダウンロードはすべて curl で行い、チェックサムを確かめます。** curl は macOS のキーチェーンにある証明書を使うので、
  情シスが配る社内の証明書(SSL の検査用)があっても通る見込みです。`HTTPS_PROXY` も尊重します。
- **チェックサムが合わないときと、署名や quarantine の問題で実行できないときは、止まって理由を出します。** 回避はしません。
- `bin/task` 本体には手を入れません。インストーラ、診断、アンインストールは `kiro/` のスクリプトとして足します。
- 出力は日本語で短くします。最後の行で、次にすることを 1 つだけ伝えます。

## 6. 決まっていないこと(人が決める、または確かめる)

1. **情シスの規程。** 管理者権限なしでも、ホームの下に実行ファイルを置いて動かすことを規程が禁じている可能性があります。
   **配る前に情シスに確認します**(技術的にできるかとは別の問題です)。
2. **リポジトリへのアクセス。** dip-ka-jo/task-hub は個人アカウントの private リポジトリです。同僚に配るには、
   次のどちらかが要ります。
   - 同僚を collaborator として招待する
   - 組織(例: dip-inc)のリポジトリに移す
3. **会社の GitHub。** Enterprise Managed Users の場合、次の点が未確認です(lessons.md の 4)。
   - 個人の Project を作れるか
   - 同僚がマージしたとき、`Closes` で自分の private な Issue が閉じるか
4. **Kiro のプラン。** 無人の実行(launchd)で `KIRO_API_KEY` を使うには Pro 以上のプランが要ります。
   会社のアカウント(IAM Identity Center)のログインだけで、無人の実行が続くかは未確認です。
5. **テンプレートの Project。** `gh project copy` を使う場合、テンプレートをどこに置くか(公開、または組織の中)を決めます。
   ワークフロー(Item closed)も写るかは PBI 1 で確かめます。

## 7. PBI(案)

| # | タイトル | 種類 | 待ち先 |
|---|---|---|---|
| 1 | かんたんセットアップ (1/5): 管理者権限なしで入れる方法とボードの作り方を調べる | 調べもの | なし |
| 2 | かんたんセットアップ (2/5): インストーラの中核(前提の確認、Python、gh、task-hub 本体、manifest) | 実装 | 1 |
| 3 | かんたんセットアップ (3/5): ログインの案内とボードの自動作成、config.ini | 実装 | 1、2 |
| 4 | かんたんセットアップ (4/5): Kiro との連携と常駐(フックとワークフローのコピー、設定、launchd) | 実装 | 2 |
| 5 | かんたんセットアップ (5/5): 「セットアップして」の steering、診断、アンインストール、初心者向けガイド | 実装とドキュメント | 2、3、4 |

各 PBI は数百行以内、テストは偽の gh と一時的な HOME で行います(既存の tests/test_task.py のやり方)。
実際の Mac での通しの確認は、最後に人が行います(使い捨ての macOS ユーザーで試すのが安全です)。
