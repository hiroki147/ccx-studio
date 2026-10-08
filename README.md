# Cube Creator X Studio

**[日本語](#日本語) | [English](#english)**

---

## 日本語

Cube Creator X(Steam版)のマスターデータ(アイテム・食べ物・武器・レシピなど)を、GUIで編集してゲームに反映する非公式ツールです。`ccx_studio.py` 1ファイルだけで動き、`res.pac` の解析から書き戻しまで行います。

> **非公式ツールです。** 開発元・パブリッシャーとは関係ありません。自己責任でご使用ください。

### できること

- アイテム、食べ物、装備(武器・防具)、レシピ、交換、ブロックの耐久、モブ、ドロップなど、マスターデータ134表の編集
- アイテム・食べ物・装備・モブの名前と説明の編集(日本語 / English)
- 食べ物・装備を「複製して追加」すると、アイテム表(`master_item`)にも新しいアイテムを自動作成
- 「全アイテムを無料クラフトに」ボタンで、材料なし・素手で作れるレシピを全アイテムに追加(「無料クラフトを取り消す」で元に戻せます)
- テクスチャ(画像)をPNGに書き出し、編集したPNGで差し替え(32bit形式とBC7形式に対応)
- アイテムのアイコンを1つずつ書き出し・差し替え、新しいアイコンの追加(アイテムの `icon_file_path` から選べます)
- 編集した内容を、配布用のmod(zip)として書き出し(ゲームの文章・画像・データは入りません)
- ワンクリックでゲームに反映、元に戻すボタン付き
- 材料や完成品のIDの横にアイテム名を表示、名前検索つきの選択ダイアログ

### 動作環境

- Python 3.8 以上(標準ライブラリのみ。追加インストール不要)
- tkinter(Linux: `sudo apt install python3-tk`)
- Linux(Steam)で作成・動作確認しています。Windowsでも動くはずですが未確認です

### 使い方

1. `ccx_studio.py` を、ゲームフォルダ(`res.pac` がある場所)に置きます。
2. 起動します。

   ```
   python3 ccx_studio.py
   ```

3. 初回は `res.pac` を自動で解析し、編集用の `tables/` フォルダ(TSV)を作ってから画面が開きます。
4. 左の一覧から表を選び、行を選んで値を直し、「適用」を押します。
5. 「ゲームに反映」を押すと、TSVを保存して `res.pac` に書き込みます。その後ゲームを起動します。
6. 元に戻すときは「ゲームを元に戻す」を押します。

画面上部のボタン:

| ボタン | 動作 |
| --- | --- |
| TSVを保存 | 編集内容を `tables/*.tsv` に保存(初回は元のTSVを `tables_orig/` に退避) |
| ゲームに反映 | 保存してから `res.pac` に書き込む |
| ゲームを元に戻す | `res.pac` のマスターデータを元の状態に戻す |
| TSVを読み直す | 保存済みのTSVを読み込み直す(未保存の編集は破棄) |
| TSVを元データから作り直す | `tables/` を `res.pac` の元データから作り直す(TSVの編集は失われる) |
| 全アイテムを無料クラフトに | 材料なし・素手で作れるレシピを、まだ無い全アイテムに追加(`master_craft`)。分類は既存レシピに合わせて自動で決める |
| 無料クラフトを取り消す | 上のボタンで追加したレシピだけを取り除く |
| クリエイティブ分類があるアイテムだけ | チェックすると、無料クラフトを追加するアイテムを絞って、追加する数を減らす |

### コマンドでの使い方

GUIを使わずに操作することもできます。

```
python3 ccx_studio.py info      # res.pac の解析結果を表示
python3 ccx_studio.py export    # tables/ を元データから作り直す
python3 ccx_studio.py build     # tables/ の内容を res.pac に反映
python3 ccx_studio.py restore   # マスターデータを元に戻す
python3 ccx_studio.py refs      # (調査用)ブロックの位置やサイズが他の場所に書かれていないか探す
```

### 作られるファイル

ツールと同じフォルダに、次のファイルが作られます。

| ファイル | 内容 |
| --- | --- |
| `tables/` | 編集用のTSV(マスターデータの各表) |
| `tables_orig/` | 最初の保存時点のTSVのバックアップ |
| `res.pac.tblk` | マスターデータ部分の元データ(数百KB) |
| `ccx_state.json` | 解析結果と状態(元のまま / 変更済み) |
| `blocks.csv` | `res.pac` のブロック一覧 |
| `mods/`、`ccx_forge.json` | Forge のmod(zip)と、状態(割り当てたID・順番・有効/無効) |
| `textures/` | 書き出したテクスチャのPNG |
| `res.pac.texbak/`、`ccx_textures.json`、`ccx_texindex.json`、`ccx_icons.json` | テクスチャ・アイコンの差し替え前のデータ、差し替えの記録、一覧 |

### 仕組み

- `res.pac` は、`0x30 + n × 0x10000` の位置から始まるzlibブロックの並びで、各ブロックの直前8バイトに展開後のサイズが入っています。
- ツールは全ブロックを走査し、`system_parameter` で始まるブロックを「マスターデータ」として特定します。
- マスターデータは、表名・列(型と列名)・行数・行データが並ぶ独自の表形式です。型は整数(4バイト)、小数(float32)、1バイト値、可変長文字列、固定長文字列で、各行の末尾に4バイトの余白が付きます。
- 反映は、元データ(`res.pac.tblk`)とTSVの差分だけを書き換えて、マスターデータのブロックを同じ位置に書き込みます。他のブロックには触りません。圧縮後のサイズが元より大きい場合は、書き込まずにエラーを出します。

### アイテムのアイコン

アイテムのアイコンは1枚ずつではなく、大きな1枚の画像(アトラス、4096×4096のBC7)にまとめて入っています。どのアイコンがどの位置かは、別のブロック(位置表)に書かれています。画面上部の「アイコン…」で、アイコンを1つずつ扱えます。

- 一覧から選ぶと、アトラスから切り出したアイコンが表示されます。「PNGに書き出し」「PNGで差し替え…」ができます。差し替えでは、そのアイコンの範囲のブロック(4×4ピクセル単位)だけを作り直し、他の部分のデータは変えません。
- 「新しいアイコンを追加…」で、アトラスの空きに新しいアイコンを入れ、位置表に1行足します。名前は `res_Item_ItemIcon_IMAGE_IMAGE_ICON_ICON_CUSTOM_001_TGA` のように自動でつきます。
- アイテム表(`master_item`)の `icon_file_path` の横にある「アイコン…」から、アイコンを選んで、アイテムに設定できます(その後「ゲームに反映」)。
- 絵の位置がずれて見えるときは、「縦を反転して切り出す」を試してください。
- 元に戻すときは、「差し替え・追加をすべて元に戻す」(または `tex-restore all`)です。
- 位置表も圧縮後のサイズが元に収まる必要があります。収まらないときは `pip install zopfli` を入れてください。
- コマンド: `icon-list`、`icon-export 番号`、`icon-replace 番号 画像`、`icon-add 画像 [名前]`

### modの書き出しと、導入ツール Forge

`ccx_studio.py` で編集した内容は、画面上部の「modとして書き出す(zip)…」で、配布用のmodにできます。mod を導入するツールは、別ファイルの `ccx_forge.py` です(`ccx_studio.py` と同じフォルダに置きます)。

- **書き出し**: 新しく作ったアイテム・食べ物・武器・レシピと、既存の値の変更だけが入ります。ゲームの元の表、テキスト、画像は入りません。名前が元のゲームの文章のままのときは、書き出しを止めます。ゲームのアイコンを差し替えた分は入りません(自分で追加したアイコンだけが入ります)。
- **Forge**: mod の zip を選ぶだけで導入できます。アイテム・テキスト・レシピのID、アイコンの場所は、導入時に自動で割り当てるので、ほかのmodと重なりません。一度割り当てたIDは保存されるので、modを足し引きしても、同じmodには同じIDが付きます。有効/無効、順番、削除ができます。同じ値を複数のmodが変えるときは、競合として表示します。
- Forge は、いつも「元のゲームのデータ」から、有効なmodを順に重ねて作り直します。**Forge で反映すると、Studio で編集した内容(`tables/`)は、ゲームには反映されません。** 逆に、Studio で「ゲームに反映」すると、Forge のmodは外れます(確認が出ます)。
- mod の形式と作り方は、[MOD_FORMAT.md](MOD_FORMAT.md) を見てください。

```
python3 ccx_forge.py                  # 画面を開く
python3 ccx_forge.py install a.zip    # modを追加
python3 ccx_forge.py apply            # ゲームに反映
python3 ccx_forge.py restore          # すべて外して元に戻す
python3 ccx_forge.py template DIR     # mod作りの見本
python3 ccx_forge.py pack DIR         # フォルダをzipにまとめる
```

**配布するときの注意**: mod の zip には、`res.pac`、書き出した表(`tables/`)、ゲームのテキスト、ゲームから取り出した画像・音声、ゲームの画像を加工した画像を入れないでください。

### テクスチャの差し替え

画面上部の「テクスチャ…」ボタンで、テクスチャの画面が開きます。

1. 一覧から選ぶとプレビューが出ます(名前つきのものは名前で探せます。名前がないものは、ブロック番号と大きさで見分けます)。
2. 「PNGに書き出し」で `textures/` にPNGを書き出し、好きなソフトで編集します。
3. 「PNGで差し替え…」で編集したPNGを選ぶと、すぐ `res.pac` に書き込まれます(ゲームを終了してから行ってください)。
4. 「この画像を元に戻す」「差し替えたものをすべて元に戻す」で戻せます。

必要なもの: `pip install pillow etcpak texture2ddecoder`

- 対応形式は、1ピクセル4バイトの無圧縮(約9割)と、1ピクセル1バイトのBC7(約1割)です。画像は元と同じ大きさにしてください(違うと縮尺します)。
- 4バイト形式の色の並び(RGBA / BGRA)は、画面上部で切り替えられます。色のついたテクスチャで見比べて、ゲーム内の見た目と合う方を選んでください。
- 差し替えた画像は、圧縮後のサイズが元に収まる必要があります。BC7は圧縮しにくいので、細かい模様やノイズを足すと収まらないことがあります。収まらないときは `pip install zopfli`(約6%小さくなります)、または画像を単純にしてください。
- 「ページの余白も使う」オプションは実験的で、実機で起動しなくなったことがあります。起動しなくなったら、「すべて元に戻す」で戻してください。
- コマンドでも使えます: `tex-list`、`tex-export 番号`、`tex-import 番号 画像`、`tex-restore 番号|all`

### 注意

- 使う前に `res.pac` のバックアップを取ることをおすすめします。
- **単独プレイ専用です。** 改変したデータでオンライン(協力・対戦)に参加しないでください。他のプレイヤーとずれたり、不正行為と見なされたりするおそれがあります。
- 既存の項目の数値や名前の変更は動作を確認しています。複製して追加した新しい項目は実験的な機能で、ゲームが新しいIDを認識するかは保証できません。
- ゲームがアップデートされて `res.pac` が変わると、ツールが検知して新しい `res.pac` を元データとして登録し直します。`tables/` は古いままなので、「TSVを元データから作り直す」を使ってください。
- 圧縮後のサイズが元の上限を超える変更は反映できません。上限に収まらないときだけ、`pip install zopfli` で入れられる圧縮ライブラリがあれば自動で使います(通常より約6%小さくなります)。それでも足りないときは、追加する行や文字を減らしてください。ページの余白を使う方法は、実機でクラッシュしたため廃止しました。
- 「全アイテムを無料クラフトに」は、全アイテムを素手で作れるようにします。アドベンチャーモードの進行に関わるアイテム(石板のかけらなど)も作れるようになるので、ゲームの遊び方が変わります。
- 壊れたときは、Steamの「ファイルの整合性を確認」で元に戻せます。
- このリポジトリにゲームのデータは含まれていません。`res.pac`、書き出したTSV、音声・画像などの再配布はしないでください。

### トラブルシューティング

| 症状 | 対処 |
| --- | --- |
| `No module named tkinter` | `sudo apt install python3-tk` |
| `res.pac が見つかりません` | ツールをゲームフォルダ(`res.pac` と同じ場所)に置く |
| `表の数が合いません` など、形式のエラー | ゲームの更新で形式が変わった可能性があります。Issueで報告してください |
| `圧縮後のサイズが上限を超えました` | `pip install zopfli` を実行してから、もう一度反映する。それでも出るときは、追加した行や文字を減らす |

### ライセンス

MIT License(`LICENSE` を参照)

「Cube Creator X」は各権利者の商標または登録商標です。本ツールは非公式であり、各権利者とは関係ありません。

### クレジット

このツールと README は Claude(Anthropic)を使って作成しました。

---

## English

An unofficial GUI tool for editing Cube Creator X (Steam) master data (items, foods, weapons, recipes and more) and applying the changes to the game. It is a single file, `ccx_studio.py`, that handles everything from analyzing `res.pac` to writing the changes back.

> **This is an unofficial tool.** It is not affiliated with the developer or the publisher. Use it at your own risk.

### Features

- Edit the 134 master data tables: items, foods, equipment (weapons and armor), recipes, exchanges, cube durability, mobs, drops and more
- Edit names and descriptions of items, foods, equipment and mobs (Japanese / English)
- Duplicating a food or an equipment entry also creates a matching new item in the item table (`master_item`)
- The "free craft" button adds material-free, hand-craftable recipes for every item (and can be undone)
- Export textures to PNG and replace them with edited PNGs (32-bit and BC7 formats)
- Export, replace and add item icons one by one (selectable from an item's `icon_file_path`)
- Export your edits as a distributable mod (zip) without any of the game's text, images or data
- Apply changes to the game with one click, and restore the original data at any time
- Item names are shown next to item IDs, with a searchable picker dialog

### Requirements

- Python 3.8 or later (standard library only; nothing else to install)
- tkinter (Linux: `sudo apt install python3-tk`)
- Developed and tested on Linux (Steam). It should work on Windows too, but that is untested

### Usage

1. Put `ccx_studio.py` in the game folder (where `res.pac` is).
2. Run it:

   ```
   python3 ccx_studio.py
   ```

3. On first launch it analyzes `res.pac` and creates a `tables/` folder (TSV files) before the window opens.
4. Pick a table on the left, pick a row, edit the values and press "適用" (Apply).
5. Press "ゲームに反映" (Apply to game). It saves the TSV files and writes them into `res.pac`. Then start the game.
6. To undo, press "ゲームを元に戻す" (Restore the game).

Buttons at the top:

| Button | Action |
| --- | --- |
| TSVを保存 (Save TSV) | Saves your edits to `tables/*.tsv` (the original TSVs are copied to `tables_orig/` on the first save) |
| ゲームに反映 (Apply to game) | Saves, then writes the changes into `res.pac` |
| ゲームを元に戻す (Restore) | Restores the original master data in `res.pac` |
| TSVを読み直す (Reload TSV) | Reloads the saved TSV files (unsaved edits are discarded) |
| TSVを元データから作り直す (Regenerate TSV) | Re-creates `tables/` from the original data in `res.pac` (your TSV edits are lost) |
| 全アイテムを無料クラフトに (Free craft for all items) | Adds a material-free, hand-craftable recipe (`master_craft`) for every item that does not have one yet. The category is chosen automatically to match existing recipes |
| 無料クラフトを取り消す (Undo free craft) | Removes only the recipes added by the button above |
| クリエイティブ分類があるアイテムだけ (Only creative-category items) | When ticked, free craft recipes are added only for items that have a creative category, to add fewer rows |

### Command line

You can also use it without the GUI:

```
python3 ccx_studio.py info      # show the analysis result of res.pac
python3 ccx_studio.py export    # re-create tables/ from the original data
python3 ccx_studio.py build     # apply tables/ to res.pac
python3 ccx_studio.py restore   # restore the original master data
python3 ccx_studio.py refs      # (for investigation) look for the block's position and size elsewhere in res.pac
```

### Files created

These files are created next to the tool:

| File | Contents |
| --- | --- |
| `tables/` | TSV files for editing (one per master data table) |
| `tables_orig/` | Backup of the TSV files taken at the first save |
| `res.pac.tblk` | The original master data block (a few hundred KB) |
| `ccx_state.json` | Analysis result and state (original / modified) |
| `blocks.csv` | List of the blocks in `res.pac` |
| `mods/`, `ccx_forge.json` | Forge's mod zips and state (assigned IDs, order, enabled/disabled) |
| `textures/` | Exported texture PNGs |
| `res.pac.texbak/`, `ccx_textures.json`, `ccx_texindex.json`, `ccx_icons.json` | Original texture/icon data before replacement, the replacement record, and the lists |

### How it works

- `res.pac` is a sequence of zlib blocks starting at `0x30 + n × 0x10000`. The 8 bytes right before each block hold its decompressed size.
- The tool scans all blocks and identifies the one that begins with `system_parameter` as the master data.
- The master data is a custom table format: table name, columns (type and name), row count, then rows. Types are 4-byte integers, float32, 1-byte values, variable-length strings and fixed-length strings. Every row ends with 4 padding bytes.
- Applying changes rewrites only the differences between the original data (`res.pac.tblk`) and your TSV files, and writes the master data block back to the same position. No other block is touched. If the compressed size would exceed the original, nothing is written and an error is shown.

### Item icons

Item icons are not stored one by one. They are packed into one large image (the atlas, a 4096x4096 BC7 texture), and a separate block (the position table) records where each icon is. The "アイコン…" (Icons) button at the top lets you work with icons one at a time.

- Pick an icon to see it cropped from the atlas. You can export it as PNG or replace it with a PNG. A replacement rebuilds only the 4x4 pixel blocks that cover the icon; the rest of the data is left untouched.
- "新しいアイコンを追加…" (Add new icon) puts a new icon into a free area of the atlas and adds one row to the position table. The name is generated automatically, such as `res_Item_ItemIcon_IMAGE_IMAGE_ICON_ICON_CUSTOM_001_TGA`.
- The "アイコン…" button next to `icon_file_path` in the item table (`master_item`) lets you pick an icon and set it on the item (then apply to the game).
- If the picture looks shifted, try "縦を反転して切り出す" (flip vertically).
- To undo, use "差し替え・追加をすべて元に戻す" (or `tex-restore all`).
- The position table must also compress to no more than its original size. If it does not fit, install `zopfli` with `pip install zopfli`.
- Command line: `icon-list`, `icon-export N`, `icon-replace N image`, `icon-add image [name]`

### Exporting mods, and the Forge installer

Your edits in `ccx_studio.py` can be exported as a distributable mod with "modとして書き出す(zip)…" at the top. The tool that installs mods is a separate file, `ccx_forge.py` (put it in the same folder as `ccx_studio.py`).

- **Export**: only newly created items, foods, weapons, recipes and changes to existing values are included. None of the game's tables, text or images are included. Export stops if a name is still the game's text. Replaced game icons are not exported (only icons you added yourself).
- **Forge**: install a mod just by picking its zip. Item, text and recipe IDs and icon positions are assigned at install time, so mods do not collide. Assigned IDs are saved, so a mod keeps the same IDs when other mods are added or removed. You can enable/disable, reorder and delete mods; values changed by several mods are shown as conflicts.
- Forge always rebuilds from the game's original data plus the enabled mods in order. **Applying with Forge does not apply your Studio edits (`tables/`) to the game. Applying with Studio removes Forge mods** (you are asked first).
- See [MOD_FORMAT.md](MOD_FORMAT.md) for the mod format and how to make one.

**When distributing**: do not put `res.pac`, exported tables (`tables/`), the game's text, images or audio taken from the game, or edited game images into a mod zip.

### Replacing textures

The "テクスチャ…" (Textures) button at the top opens the texture window.

1. Pick a texture from the list to see a preview (named textures can be searched by name; unnamed ones are identified by block number and size).
2. "PNGに書き出し" (Export PNG) writes a PNG to `textures/`. Edit it with any image editor.
3. "PNGで差し替え…" (Replace with PNG) writes your edited PNG into `res.pac` immediately (close the game first).
4. "この画像を元に戻す" (Restore this) and "差し替えたものをすべて元に戻す" (Restore all) undo replacements.

Requires: `pip install pillow etcpak texture2ddecoder`

- Supported formats are uncompressed 4 bytes per pixel (about 90%) and BC7 at 1 byte per pixel (about 10%). Use the same image size as the original (otherwise it is resized).
- The channel order of 4-byte textures (RGBA / BGRA) can be switched at the top. Compare with a colored texture and choose the one that matches the in-game look.
- A replaced image must compress to no more than the original compressed size. BC7 data compresses poorly, so adding fine detail or noise may not fit. If it does not fit, install `zopfli` (about 6% smaller) or simplify the image.
- The "use page padding" option is experimental and has made the game fail to start. If that happens, use "Restore all".
- Command line: `tex-list`, `tex-export N`, `tex-import N image`, `tex-restore N|all`

### Notes

- Please back up `res.pac` before using the tool.
- **Single-player use only.** Do not join online (co-op / versus) games with modified data. It may desync with other players or be treated as cheating.
- Editing existing values and names is confirmed to work. Newly duplicated entries are experimental, and there is no guarantee that the game recognizes new IDs.
- When a game update changes `res.pac`, the tool detects it and registers the new `res.pac` as the original data. `tables/` stays old, so use "TSVを元データから作り直す" (Regenerate TSV).
- Changes whose compressed size exceeds the original limit cannot be applied. If you install the optional compression library with `pip install zopfli`, the tool uses it automatically when a change does not fit (about 6% smaller than normal). If it still does not fit, reduce the added rows or text. Using the padding at the end of the page was removed because it crashed the real game.
- The free craft button makes every item craftable by hand, including items tied to Adventure mode progression (such as slate fragments), which changes how the game plays.
- If something breaks, use Steam's "Verify integrity of game files" to restore the original.
- This repository contains no game data. Please do not redistribute `res.pac`, exported TSV files, audio or images.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No module named tkinter` | `sudo apt install python3-tk` |
| `res.pac が見つかりません` (res.pac not found) | Put the tool in the game folder, next to `res.pac` |
| Format errors such as `表の数が合いません` (table count mismatch) | The game format may have changed with an update. Please report it as an issue |
| `圧縮後のサイズが上限を超えました` (compressed size exceeds the limit) | Run `pip install zopfli` and apply again. If it still fails, reduce the added rows or text |

### License

MIT License (see `LICENSE`)

"Cube Creator X" is a trademark or registered trademark of its respective owners. This tool is unofficial and is not affiliated with them.

### Credits

This tool and this README were created with Claude (Anthropic).
