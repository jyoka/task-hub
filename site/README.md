# site: task-hub の LP

task-hub の LP(1 ページ)です。**今は公開しません。** 手元で開いて見ます。GitHub Pages に出すかは運営者が決めます(下の「公開するとき」)。

```sh
python3 -m http.server --bind 127.0.0.1 --directory site 8000   # リポジトリの一番上で。止めるときは Ctrl+C
```

ブラウザで http://127.0.0.1:8000/ を開きます。日本語は http://127.0.0.1:8000/?lang=ja です。

- 要るのは Python 3 だけです。task-hub と同じく、新しい依存はありません
- `site/assets` は `../assets` へのリンク(シンボリックリンク)です。LP は `assets/brand/` と `assets/media/` を、同じ場所の `assets/` から読みます
- 外から読み込むもの(CDN のスクリプト、Web フォント)はありません。`index.html` の CSP(meta)が、ほかの場所からの読み込みを止めます
- `site/index.html` を `file://` で直に開いても、Chrome 156 では絵と CSS が出ました。ほかのブラウザでは確かめていないので、上のように http で開きます
- 文と絵の元は [docs/brand.md](../docs/brand.md) と [assets/](../assets/) です。1 文を変えるときは、brand.md の決まりどおり全部を一度に変えます

## 中身

| ファイル | 中身 |
|---|---|
| `index.html` | ページ。見出し、分解のアニメ、できること、3 手で始める、比べる、フッターの順。英語と日本語を両方書き、`<html lang>` で出し分ける |
| `site.css` | 見た目。色、字、角丸、動きの長さは `assets/brand/tokens.css` の変数を使う |
| `site.js` | 言葉と見た目の切り替え、分解のアニメ、動く画像の再生。ライブラリは使わない |
| `llms.txt` | ページの中身を文にしたもの(英語) |
| `favicon.svg` | タブの印(3 本の柱) |
| `assets` | `../assets` へのリンク |

- 分解のアニメ: スクロールの位置から `--sep`(層の離れ方)と今の層を決め、CSS の 3D の変形(`perspective`、`rotateX`、`translateZ`)で動かします。
  層は [brand.md の 4 節](../docs/brand.md#4-分解の絵の台本)の 8 つで、色は誰がするか(あなた、task-hub のコード、エージェント)です。
  レビューの層(05)では、`needs changes` の印が出て、続けてスクロールすると `pass` に変わります
- 動かさないとき: `prefers-reduced-motion` のとき、高さが 560 px より低い画面(横にしたスマホなど)、コンテナクエリの単位(`cqw`、`cqh`)を
  使えないブラウザーでは、`<html>` に `.motion` を付けず、8 つの層を止まった絵で縦に並べます
- 動く画像(`assets/media/flow.webm`)は、`prefers-reduced-motion` のときだけ自分では再生しません(再生のボタンで見られます)。
  WebM だけなので、WebM を再生できないブラウザーでは映りません。そのときのために、下の文に GIF へのリンクを置いています
- 英語が先です。日本語は右上のボタンか `?lang=ja` で切り替えます。ダークとライトは OS の設定に従い、右上のボタンで切り替えます。
  ボタンで選んだものは `localStorage` に残します。`?lang=` は残しません。ボタンを押すと、アドレスの `?lang=` を消します(次に開いたときに戻らないように)
- 画像は `python3 tests/media.py` が撮った本物の画面です([docs/media.md](../docs/media.md))。撮り直すと、LP の絵も変わります。
  機能のカードの絵は、画面の一部を CSS で拡大して切り出しています(`site.css` の `.crop-*`)。画面の大きさが変わったら、切り出す所も直します
- 機能のカードは、brand.md の 3 節の 3 本の柱の順(安心、軽さ、信頼)に並べ、見出しの上に柱の名前を出します
- 絵のない機能(Goal の確認、止まった後の再開、通知、コードが残す記録)のカードは、コマンドと印の文字だけです
- docs へのリンクは GitHub のリポジトリ(`https://github.com/jyoka/task-hub`)を指します。docs は日本語です

## 確かめる

`python3 tests/run.py test_site` が、ブラウザを使わずに HTML、CSS、JS を読んで確かめます。

- ボタンとリンクの先がある(ページの中の `#...`、`assets/` のファイル、GitHub の docs のファイルと見出し)
- 外から読み込まない(CSP、`http` で始まる `src`、`@import`、`url(http`、`fetch` などがない)
- 1 文が brand.md と同じ。機能のカード 8 枚と 8 つの層が brand.md の順
- `prefers-reduced-motion` で動かさない作り(`site.js` と `site.css`)
- 運営者の私的な名前が出ない

ブラウザでの動きは、手元の Chrome で確かめます。リポジトリに確かめの道具は足しません。

1. 上の `python3 -m http.server` で開く
2. Chrome の DevTools で、次を見る
   - 横幅: デバイスのツールバー(⌘⇧M)で 390 と 320 にし、横にスクロールできないこと
   - スクロール: 「One card, layer by layer.」から下へスクロールし、左の番号が 01 から 08 に進むこと。05 で `needs changes`、その後 `pass` が出ること
   - 動きを止める: ⌘⇧P で「Rendering」を開き、「Emulate CSS media feature prefers-reduced-motion」を `reduce` にして再読み込みし、8 つの層が縦に並んで止まり、動く画像が自分で再生しないこと
   - 外への通信: Network のタブで、`127.0.0.1` 以外への要求がないこと
3. スクリーンショットは Chrome の headless で撮れる(ウィンドウを出さない)

   ```sh
   CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
   "$CHROME" --headless=new --hide-scrollbars --user-data-dir="$(mktemp -d)" --window-size=1440,900 --screenshot=/tmp/lp-1440.png http://127.0.0.1:8000/
   "$CHROME" --headless=new --hide-scrollbars --user-data-dir="$(mktemp -d)" --window-size=390,844 --screenshot=/tmp/lp-390.png http://127.0.0.1:8000/
   # 動きを止めた形(層が縦に並ぶ)。高い窓で撮ると層まで写る
   "$CHROME" --headless=new --hide-scrollbars --user-data-dir="$(mktemp -d)" --force-prefers-reduced-motion --window-size=1440,3000 --screenshot=/tmp/lp-still.png http://127.0.0.1:8000/
   ```

2026-10-29 に、Chrome 156(macOS)で上の全部を確かめました。スクロールの途中の形や番号を自動で確かめるときは、Chrome の DevTools Protocol を
`--remote-debugging-pipe` で動かす使い捨てのスクリプトを手元で書いて使いました(リポジトリには入れていません)。Safari と Firefox では確かめていません。

## 公開するとき(運営者が決めたとき)

今はしません。公開を決めたら、次の順で行います。

1. [docs/brand.md の 7 節](../docs/brand.md#7-公開の前に直すもの)の「公開の前に直すもの」を見る。docs の私的な名前は直した(2026-10-29)。残した所(「タスク 252」のような番号、docs の外のコードとテスト)を、公開の前に直すかを決める
2. 出すフォルダーの作り方を決める。`-L` で `site/assets` のリンクの先(`assets/brand/` と `assets/media/`)を中に写し、1 つのフォルダーにする。
   workflow の中で作る(手元では作らない。`_site/` は `.gitignore` に入っていないので、手元で作ったら消す)

   ```sh
   rm -rf _site && cp -RL site _site && rm _site/README.md
   ```

3. GitHub Pages に出す。リポジトリの Settings → Pages で、Source を「GitHub Actions」にし、`_site` を `actions/upload-pages-artifact` と
   `actions/deploy-pages` で出す workflow を `.github/workflows/` に足す。workflow はそのときに作る(main への push で 2 の手順を動かし、出す)。
   workflow には `permissions`(`pages: write`、`id-token: write`)と、`github-pages` の environment が要る
4. 出したページ(`https://jyoka.github.io/task-hub/`)を、ダークとライト、英語と日本語、スマホの幅で開いて確かめる。上の「確かめる」と同じことを、出した URL でも見る
5. 出した URL を GitHub の About の Website に書く(運営者)

- `llms.txt` は `https://jyoka.github.io/task-hub/llms.txt` に出る。ドメインの一番上(`/llms.txt`)ではない。独自のドメインを使うと一番上に来る
- 独自のドメインを使うかは、そのときに決めます
