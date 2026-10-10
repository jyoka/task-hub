# リリース

task-hub の変更は、1 コミットごとではなく 1 リリースごとに知らせます。利用者は、リリースノートを読めば
「何が変わったか」と「更新で何をすればよいか」がわかります。ここには、版の付け方、リリースの手順、
リリースノートの型を書きます。

リリースの一覧: https://github.com/jyoka/task-hub/releases

## 版の付け方

- 版は [semver](https://semver.org/lang/ja/)(`MAJOR.MINOR.PATCH`)です。
- 版は `bin/task` の `VERSION` に書きます。`task --version` で出る値です。
- タグは `v<VERSION>` です(`VERSION = "0.6.0"` なら `v0.6.0`)。**タグの名前と、そのタグのコミットの `VERSION` は
  必ず一致させます。** 一致しないと、`task --version` とリリースの一覧で版の名前が食い違います。
- 1.0.0 になるまでは、次のように上げます。

| 上げる桁 | いつ | 例 |
|---|---|---|
| MINOR(`0.6.0` → `0.7.0`) | 機能を足したとき。更新で利用者の作業が要るとき(設定、Project の欄、Kiro のコピーし直しなど) | 0.5 で Project に Base branch の欄が要るようになった |
| PATCH(`0.6.0` → `0.6.1`) | 直しだけで、更新で要る作業が `task update` だけのとき | 表示の崩れを直す |

**タグは消したり、付け替えたりしません。** 利用者の clone は、手元にあるタグを信じています。直したいときは、
直したコミットで次の版を出します。

Kiro IDE 版の配布に使う `kiro-v<数字>` のタグは、これとは別の決まりです([kiro-ide.md](kiro-ide.md#9-配布する版を出す))。
インストーラが見るのは `kiro-v*` だけなので、`v*` のタグを付けても Kiro IDE 版の配布は変わりません。

## リリースの手順

1. **VERSION を上げる PR を出して、マージします。** `bin/task` の `VERSION` を新しい版にします。
   リリースノートの下書き(下の型)を PR の本文に書いておくと、3 でそのまま使えます。
   README と docs が、この版の使い方と合っているかも確かめます(README のコマンドの表はテストが確かめます。
   構成は [CONTRIBUTING.md](../CONTRIBUTING.md#readme-の構成))。
2. **main にタグを付けて push します。** タグを付ける前に、main の `VERSION` が新しい版になっていることを確かめます。

   ```
   git fetch origin
   git show origin/main:bin/task | grep '^VERSION'       # VERSION = "0.7.0" と出ること
   git tag -a v0.7.0 -m "v0.7.0" origin/main
   git push origin v0.7.0
   ```

3. **GitHub のリリースを作ります。** ノートは、下の型で書いたファイルから読みます。

   ```
   gh release create v0.7.0 -R jyoka/task-hub --verify-tag --title v0.7.0 --notes-file notes.md
   ```

   `--verify-tag` は、タグが GitHub にまだないときに止めるためのものです(付けないと、gh がその場で main に
   タグを作ります。2 で確かめたコミットと違うかもしれません)。
4. **確かめます。**

   ```
   git ls-remote --tags origin 'v*'                      # v0.7.0 が出ること
   gh release view v0.7.0 -R jyoka/task-hub              # ノートが読めること
   ```

## リリースノートの型

読むのは task-hub の利用者です。コードの説明ではなく、利用者から見た変化を書きます。

```markdown
## 変わったこと

- <利用者から見た変化。1 行に 1 つ。関係する PR の番号を添える(#12)>

## 更新で要る作業

いつもの更新(`task update`。docs/setup.md の「インストール」)に加えて:

- <この版だけで要る作業。なければ「なし」と書く>
```

「更新で要る作業」には、次のようなものを書きます。

- Kiro IDE のフックとワークフローの定義を新しく入れること(新しい定義が増えたとき。入っている定義のコピーし直しは
  `task update` が行うので書かなくてよい。[setup.md](setup.md#インストール))
- Project の欄の追加や変更(例: 0.5 の Base branch)
- `config.ini` の設定の追加や変更
- launchd の plist の書き換えと登録し直し(plist に書く中身が変わったとき。[setup.md](setup.md#launchd-で常駐させるターミナルを開いておかない))
- スキルのリンクの追加(`skills/` に新しいスキルが増えたとき)
