# Slackトリアージ(⌃⌥S)

Slack のスレッドをコピーして **⌃⌥S**(control + option + S)を押すと、Kiro がスレッドを整理して、task-hub に登録する
タスクの案を作ります。タスクにするかどうかは Kiro は決めず、毎回あなたが決めます。かんたんセットアップ(`kiro/install.sh` の
「11. Slackトリアージ」)で、全員に入ります。

- Slack には何も入れません(アプリの承認は要りません)。Slack から見れば、あなたが文字をコピーしているだけです
- スレッドの文章を送る先は、ふだん使っている Kiro だけです
- 整理する Kiro は、ツールを一切持たない専用のエージェント(`slack-triage/.kiro/agents/slack-triage.json`)です。
  スレッドの中に「〜を実行して」のような文があっても、整理するだけで何も実行できません。`task new` を実行するのは、
  あなたが「登録」を押したときの、このプログラムだけです

## 使い方

1. Slack でスレッドを開き、**文章をドラッグして選び、⌘C でコピー**します
   - 元のスレッドのリンク(メッセージの「⋯」→「リンクをコピー」)も一緒にコピーしておくと、カードに「出典」として残ります
2. **⌃⌥S** を押します(⌃ は control、⌥ は option)
   - **初めて押したとき** だけ、あなたの名前(Slack の表示名。あだ名も読点で区切って書けます)と、登録先になりそうな
     リポジトリを聞きます
3. 30 秒ほどで、「タスクにしますか？」のダイアログが出ます。上に **スレッドの整理**(何の話か、誰が誰に何を頼んだか、
   決まったこと、決まっていないこと)、下に **タスク案**(タイトル、リポジトリ、ゴール)が出ます。関心事が複数あれば、
   タスク案を 1 件ずつ聞きます

| ボタン | すること |
|---|---|
| 登録 | task-hub の Backlog にカードを作ります。本文は ゴール →「スレッドの整理」→ 出典 の順です(着手させるときは、いつもどおり Ready に移します) |
| 内容を直す | タイトルとゴール(エージェントへの指示)を直してから登録できます |
| 不要 | 何もしません |

お知らせだけのスレッドや、スレッド内で解決済みのものでも、Kiro は「もしタスクにするなら」の案を 1 件作ります。
整理の 1 行目に「依頼はありません」「解決済みです」などと出るので、見て「不要」を押してください。

### 登録先のリポジトリ

- 登録できるのは、**あなたの GitHub アカウント配下のリポジトリだけ**です(gh でログインしているアカウント。例: `<あなたのアカウント>/…`)。
  会社(organization)のリポジトリは候補に出さず、入力しても登録しません
- カード(Issue)はいつもどおりボードの issues リポジトリ(例: `<あなたのアカウント>/tasks`)にできます。ここで選ぶのは、
  エージェントが作業する先(Target repo)です
- **調査・回答のまとめ** のタスク(コードを変えない)は、選ばなくてもボードの issues リポジトリを作業先にします
- **コードを直す** タスクの候補は、初めて ⌃⌥S を押したとき(または `slack-triage setup`)に選びます

試すだけなら、ターミナルで `slack-triage practice` を実行します(練習用のスレッドで整理まで動き、登録はしません)。

## コマンド

| コマンド | すること |
|---|---|
| `slack-triage check` | 動くための条件がそろっているかを確かめる(× の行の → が次にすること) |
| `slack-triage practice` | 練習(登録はしない) |
| `slack-triage setup` | 名前と登録先リポジトリを選び直す |
| `slack-triage key t` | 起動キーを ⌃⌥T にする(a〜z)。修飾キーも変えるなら `slack-triage key t ctrl,opt,cmd` |
| `slack-triage off` / `on` | 起動キーを止める / 再開する。止めている間は、`kiro/install.sh` をもう一度実行しても止めたままです |

## うまくいかないとき

| こんなとき | すること |
|---|---|
| ⌃⌥S を押しても何も起きない | control と option を押しながら S を押しているか確かめる。それでもなら `slack-triage check` |
| ほかのアプリでも ⌃⌥S が反応する | `slack-triage key t` などで別のキーにする(macOS は、同じキーを使うアプリがあっても教えてくれません) |
| 「Kiroが失敗しました」 | ターミナルで `kiro-cli login` |
| 「登録に失敗しました」 | チャットで「診断して」。GitHub のログインが切れていれば、案内どおりにログインし直す |
| 「文字化けしている」 | Slack でコピーし直して、もう一度 ⌃⌥S |
| 整理やタスク案がおかしい | 「内容を直す」で直してから登録できます。何度も起きるなら task-hub の担当者に、そのスレッドの種類を伝えてください(ログには、タスク案の件数と登録したかだけが残り、スレッドの本文や整理結果は残しません) |

## 置かれるもの

| もの | 場所 |
|---|---|
| 本体 | `~/.local/lib/task-hub/slack-triage/`(task-hub の clone の中) |
| コマンド | `~/.local/bin/slack-triage`(インストーラが確かめた Python で動かす wrapper) |
| 起動キーを待つ常駐 | `~/Library/LaunchAgents/com.task-hub.slack-triage.plist`(ログインしている間。`slack-triage-hotkey`) |
| 起動キーを待つプログラム | `~/.local/lib/task-hub/slack-triage/bin/slack-triage-hotkey`(インストーラがこの Mac でビルドしたもの) |
| あなたの設定 | `~/.config/task-hub/slack-triage.json`(名前、候補リポジトリ、起動キー、止めているか) |
| ログ | `~/.local/state/task-hub/slack-triage.log`(タスク案の件数、登録したか)、`slack-triage-hotkey.err.log` |

アンインストール(`kiro/uninstall.sh`)は、コマンドと常駐を消します。あなたの設定は残します。

## しくみ(開発する人向け)

- 起動キーは `slack-triage/hotkey/main.swift`(macOS の `RegisterEventHotKey`)。アクセシビリティや入力監視の
  権限は要りません。キーは `--config` の JSON(`hotkey_key`、`hotkey_mods`)から読むので、`slack-triage key` は
  plist を書き換えずに常駐を起動し直すだけです。キーを登録できたら `--status` のファイルに `ok …` を書きます
- `slack-triage/bin/slack-triage-hotkey` はリポジトリに入れていません。インストーラ(「11. Slackトリアージ」)が
  `sh slack-triage/hotkey/build.sh` で、使う人の Mac の上でビルドします(Intel / Apple シリコン両対応、ad-hoc 署名)。
  swiftc は Xcode の Command Line Tools(前提の git と同じもの)に入っています。`main.swift` が変わった版になると、
  次にインストーラを実行したときにビルドし直します
- 本体は Python の標準ライブラリだけ(`slack-triage/app/slack_triage/`)。整理とタスク案の指示は `core.py` の `build_prompt`、
  ダイアログは AppleScript(`macui.py`。表示する文章は引数で渡し、スクリプトに埋め込みません)
- テスト: `python3 -m unittest tests.test_slack_triage`(整理から登録までの流れを偽の画面で)、インストーラの段階は
  `tests/test_install.py`
