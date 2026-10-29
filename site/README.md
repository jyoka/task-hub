# site: task-hub の LP

task-hub の LP(1 ページ)です。**https://jyoka.github.io/task-hub/ で公開しています**(GitHub Pages)。
main に入ると、workflow が出し直します(下の「公開」)。直すときは、次のように手元で開いて見ます。

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

## 公開

2026-10-30 に、運営者が公開を決めました。URL は https://jyoka.github.io/task-hub/ です。日本語は https://jyoka.github.io/task-hub/?lang=ja です。

- `llms.txt` は https://jyoka.github.io/task-hub/llms.txt にあります。ドメインの一番上(`/llms.txt`)ではありません。独自のドメインを使うと一番上に来ます
- 独自のドメインは使っていません。使うかは、運営者が決めます
- 出す前に私的な名前を直した記録は、[docs/brand.md の 7 節](../docs/brand.md#7-公開の記録)にあります

### 出し方

[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) が出します。リポジトリの Settings → Pages の Source は「GitHub Actions」です。

1. main への push で動きます。`site/`、`assets/`、`docs/brand.md`、この workflow のどれかが変わったときだけです。Actions のタブの
   `pages` → Run workflow で、手で動かすこともできます
2. `build` の job が、`python3 tests/test_site.py` で LP を確かめます。落ちたら出しません
3. 出すフォルダー `_site` を作ります。`-L` で `site/assets` のリンクの先(`assets/brand/` と `assets/media/`)を中に写し、1 つのフォルダーにします

   ```sh
   rm -rf _site && cp -RL site _site && rm _site/README.md
   ```

   `_site` は workflow の中で作ります。`.gitignore` に入っていないので、手元で作ったら消します
4. `actions/upload-pages-artifact` が `_site` を上げ、`deploy` の job が `actions/deploy-pages` で出します

- `deploy` の job だけが `pages: write` と `id-token: write` を持ちます。ほかは `contents: read` です。秘密は使いません
- `github-pages` の environment は main からしか出せません。ほかのブランチで手で動かすと、`build` だけが動きます
- action は、コミットの SHA で版を固定しています。上げるときは、SHA と横の版の番号を一緒に直します

### 出し直し方

- 直したものを main に入れると、出し直します。1 回に 1 つずつ出し、動いている途中のものは止めません
- 中身が同じまま出し直したいとき(Pages の不調など)は、Actions のタブの `pages` → Run workflow を main で動かします
- 前の版に戻すときは、main で直す PR を出してマージします

### 止め方

- しばらく出し直さない: Actions のタブの `pages` → `...` → Disable workflow。今のページは残ります。戻すときは Enable workflow
- Pages を外す(ページが消える): `gh api -X DELETE repos/jyoka/task-hub/pages`(Settings → Pages からも外せます)。
  外したら、上のとおり workflow も止めます。外したままの `deploy` がどうなるかは確かめていません。
  戻すときは、Source を「GitHub Actions」にし直し(`gh api -X POST repos/jyoka/task-hub/pages -f build_type=workflow`)、
  workflow を Enable にして Run workflow で動かします
- やめると決めたら、Pages を外してから `.github/workflows/pages.yml` を消す PR を出します

### 出した後の確かめ

出した URL で、上の「確かめる」の 2 と同じことを見ます。

1. https://jyoka.github.io/task-hub/ を、ダークとライト(右上のボタン)、英語と日本語(右上のボタンと `?lang=ja`)で開く
2. スマホの幅: DevTools のデバイスのツールバーで 390 と 320 にし、横にスクロールできないこと
3. 外への通信: Network のタブで、`jyoka.github.io` 以外への要求がないこと(docs へのリンクは、押したときだけ `github.com` を開く)
4. https://jyoka.github.io/task-hub/llms.txt が文で出ること
5. 出した URL を GitHub の About の Website に書く(運営者)
