# 弱い PC での計測

task-hub が性能の低い PC でも軽く動くかを、`tests/bench.py` で測ります。CPU を使い切る負荷テストではありません。
弱い PC で人が感じるものを測ります。

- 常に動くプロセス(`task watch`、`task list --watch`)の重さ: 常駐のメモリと、1 分あたりの CPU 時間
- コマンド(`task list`、`task events`)が出力し終えるまでの時間と、最大のメモリ

普段の変更のたびには動かしません。頼まれたときと、リリースの前に人が動かします
([release.md](release.md#リリースの手順))。

## 動かし方

```sh
python3 tests/bench.py                    # 既定: 各 5 回の中央値。task watch は 125 秒(約 2 分半)
python3 tests/bench.py --quick            # 30 秒ほど。各 3 回、task watch は 15 秒
python3 tests/bench.py --efficiency-cores # macOS: 効率コアだけで動かす(弱い PC に近づける)
```

Windows では `python3` の代わりに `py -3` を使い、パスは `tests\bench.py` と書きます。

| オプション | 中身 |
|---|---|
| `--quick` | 同僚が自分の PC で動かす用。30 秒ほどで終わる |
| `--efficiency-cores` | macOS だけ。`taskpolicy -b` で動かす。Apple Silicon では効率コアだけを使う |
| `--runs N` | 各コマンドを動かす回数(既定 5、`--quick` は 3) |
| `--watch-seconds N` | `task watch` を動かす秒数(既定 125、`--quick` は 15) |

終了コードは、目安をすべて満たせば 0、満たさないものがあれば 1、計測そのものが失敗したら 2 です。

## どこで動かすか

| 場所 | いつ | 動かし方 |
|---|---|---|
| 開発している Mac | リリースの前 | 既定の実行と `--efficiency-cores` |
| 同僚の PC(古い Windows、Mac) | 頼んだとき | `--quick` |
| GitHub Actions の Windows | push のたび | 動くことだけを確かめる(`tests/test_windows.py` の `WindowsBenchTest`)。値は見ない |

CI の値は目安と比べません。CI のマシンは、ほかの仕事と同居していて値が揺れるためです。

## 同僚に頼むときの手順

設定、GitHub へのサインイン、`gh` は要りません。task-hub をセットアップしていない PC でも動きます。

1. Python 3.10 以上があることを確かめてもらう。Mac は `python3 --version`、Windows は `py -3 --version` です
2. task-hub を取得してもらう。`git clone https://github.com/jyoka/task-hub` か、GitHub の「Code」から ZIP を
   ダウンロードして展開します。task-hub を入れている人は、入っている clone(`~/.local/lib/task-hub`)で動かせます
3. いつもの使い方の状態で動かしてもらう。動画会議やビルドのような重い処理の最中は避けます。値が揺れるためです
4. 取得したフォルダで、次を動かしてもらう(30 秒ほど)

   ```sh
   python3 tests/bench.py --quick        # Mac
   py -3 tests\bench.py --quick          # Windows(PowerShell)
   ```

5. 出力の全部(`machine:` の行から `done in` の行まで)を、Issue かチャットに貼ってもらう

出力に入るのは、OS、CPU の名前、コア数、メモリ、Python の版と、計測の値だけです。ユーザー名やファイルの中身は
入りません。計測が失敗したときのエラーにだけ、一時フォルダのパスが入ることがあります。

## 出力の読み方

`--quick` を開発している Mac で動かした例です(2026-10-11)。

```
machine: macOS 26.6.2, arm64 | CPU: Apple M1 Pro, 10 cores (8 performance, 2 efficiency) | memory: 16.0 GB | Python 3.10.4
bench: quick, 3 run(s) each, task watch for 15 s, one process at a time; a throwaway HOME and a fake GitHub
...
| command | cards | time (median) | peak memory | resident memory | CPU per minute |
|---|---|---|---|---|---|
| `task list` | 12 | 56 ms | 27.1 MB | - | - |
| `task list` | 1000 | 73 ms | 30.1 MB | - | - |
| `task events` | - | 54 ms | 26.8 MB | - | - |
| `task list --watch` | 12 | - | - | 27.1 MB | - |
| `task watch` | 12 | - | - | 27.3 MB | 0.06 s (0.10%) |

targets (first guesses, docs/benchmark.md):
PASS: task watch resident memory < 50 MB: 27.3 MB
PASS: task watch CPU < 1% on average: 0.10%
PASS: task list (12 cards, fresh cache) < 300 ms: 56 ms
PASS: task list (1000 cards, fresh cache) < 300 ms: 73 ms
note: task watch read the fake GitHub 3 time(s) in 15 s; the CPU of its gh calls is not counted, only task watch's own
done in 19 s
```

| 列 | 中身 |
|---|---|
| `time (median)` | 起動してから終わるまでの時間の中央値。Python の起動も入る |
| `peak memory` | そのコマンドが使った最大のメモリ(常駐セット) |
| `resident memory` | 常に動くコマンドを動かしている間に見た、常駐のメモリの最大 |
| `CPU per minute` | `task watch` が 1 分に使う CPU 時間と、1 コアに対する割合 |

## 目安

初めの値です。同僚の PC で測った値を見て直します。

| 何を | 目安 | 理由 |
|---|---|---|
| `task watch` の常駐のメモリ | 50 MB 未満 | 一日中動く。エージェント 1 つ(365〜657 MB)に比べて小さいこと |
| `task watch` の CPU | 平均 1% 未満(1 コアに対して) | 一日中動く。ファンや電池に響かないこと |
| `task list`(キャッシュが新しい) | 300 ms 未満 | ペインやステータスラインが何度も呼ぶ。待たされたと感じないこと |

`task list` の目安は、カード 12 枚と 1000 枚の両方に当てます。

## 今わかっている値

### 2026-10-11、利用者の Mac(Apple M1 Pro、10 コア: 性能 8、効率 2、16 GB)

`tests/bench.py` を作る前に、同じ測り方を手で行った値です。

| カード | コマンド | 時間(中央値) | 最大メモリ |
|---|---|---|---|
| 12 | `task list` | 58 ms | 27 MB |
| 1000 | `task list` | 125 ms | 37 MB |
| - | `task events` | 50 ms | 27 MB |
| 12 | `task list --watch`(常駐) | - | 27 MB |
| - | エージェント(Claude Code)1 つ | - | 365〜657 MB |

### 2026-10-11、同じ Mac で `tests/bench.py`

| コマンド | 既定 | `--quick` | `--quick --efficiency-cores` |
|---|---|---|---|
| `task list`、12 枚 | 54 ms、27.0 MB | 56 ms、27.1 MB | 261 ms、26.8 MB |
| `task list`、1000 枚 | 75 ms、34.8 MB | 73 ms、30.1 MB | 354 ms、34.5 MB |
| `task events` | 57 ms、26.9 MB | 54 ms、26.8 MB | 250 ms、26.7 MB |
| `task list --watch` の常駐 | 26.9 MB | 27.1 MB | 26.7 MB |
| `task watch` の常駐 | 27.7 MB | 27.3 MB | 26.8 MB |
| `task watch` の CPU | 0.03 秒/分(0.05%) | 0.06 秒/分(0.10%) | 0.17 秒/分(0.28%) |
| かかった時間 | 132 秒 | 19 秒 | 22 秒 |

- 効率コアだけにすると、`task list` は 4〜5 倍遅くなり、1000 枚で目安の 300 ms を超えました
- 1000 枚の `task list` は、手で測った 125 ms より速く出ました。カードの本文の長さなど、ボードの中身が違うためと
  推測しています(確かめていません)
- 古い Windows の PC と、Intel の Mac の値はまだありません

## 測り方

`tests/bench.py` は Python の標準ライブラリだけで書いています。

- **使い捨ての HOME**: 一時フォルダに HOME を作り、設定と偽物のボードを置きます。`HOME`(Windows は
  `USERPROFILE`)をそこに向け、`TASK_`、`XDG_`、`CLAUDE_`、`GH_`、`GITHUB_`、`HERDR_` で始まる環境変数は渡しません。
  本物の `~/.config/task-hub` と `~/.local/state/task-hub` は読みも書きもしません。終わると一時フォルダを消します
- **偽物の GitHub**: テストと同じ偽物の `gh`(`tests/test_task.py` の `FAKE_GH`)を `TASK_GH` に指定します。
  Windows では `tests/test_windows.py` と同じく、pip の起動用の .exe に入れて動かします。
  `TASK_NO_UPDATE_NOTIFIER=1` で、更新の確認(git の origin への問い合わせ)もしません
- **ボード**: カード 12 枚と 1000 枚の 2 つ。本文は 1.6 KB ほどです。Status は Backlog、Blocked、Done だけにします。
  Ready があると `task watch` が実行を始め、In review があると PR を探すためです
- **`task list`**: 1 度動かしてキャッシュ(`board-cache.json`)を作ってから測ります。測っている間に偽物の GitHub が
  読まれたら、キャッシュが使われなかったという `note:` の行を出します
- **`task events`**: 500 行の `events.jsonl` を置いて測ります
- **`task list --watch`**: 出力を捨てて動かし、3 秒(既定は 5 秒)の間、0.5 秒ごとに常駐のメモリを見ます
- **`task watch`**: 偽物の GitHub を相手に動かし、CPU 時間と常駐のメモリを見ます。起動から測るので、起動と最初の
  確認の分だけ、実際の 1 分より多めに出ます。1 分より短く動かしたときは、その分を 1 分の値とします。
  `gh` の呼び出し(1 分に 1〜2 回)の CPU は数えず、`task watch` のプロセスだけを数えます
- **1 度に 1 プロセス**: コマンドは 1 つずつ順に動かし、終わってから次を始めます。並べては動かしません
- **時間**: `time.perf_counter` で、起動の直前から終わるまでを測ります

OS ごとに、メモリと CPU の読み方が違います。

| OS | 最大のメモリ | 常駐のメモリと CPU 時間 |
|---|---|---|
| macOS | `os.wait4` の `ru_maxrss`(バイト) | `ps -o time=,rss=` |
| Linux | `os.wait4` の `ru_maxrss`(KB) | `/proc/<pid>/stat` と `statm` |
| Windows | `ctypes` で `GetProcessMemoryInfo` の `PeakWorkingSetSize` | `GetProcessMemoryInfo` の `WorkingSetSize` と `GetProcessTimes` |

Windows では `PYTHONUTF8=1` を付けて動かします。`task.cmd` と `windows/task-watch.ps1` が付けるのと同じで、
付けないと `bin/task` が UTF-8 のモードで自分をもう 1 度起動し、プロセスが 2 つになるためです。
常駐の `task watch` を動かし続ける PowerShell(`task-watch.ps1`)のメモリは数えていません。

`--efficiency-cores` の `taskpolicy -b` は、プロセスをバックグラウンドの優先度にします。Apple Silicon では効率コア
だけで動き、ディスクの読み書きも後回しになります。弱い PC と同じではなく、近づけるだけです。

## 確かめていないこと

- Windows の実機では、まだ動かしていません(2026-10-11)。GitHub Actions の Windows で動くことは
  `WindowsBenchTest` が確かめますが、この PR の時点では結果を見ていません
- Linux では動かしていません。`/proc` を読む部分は確かめていません
