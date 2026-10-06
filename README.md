# Cube Creator X Studio
<img width="1440" height="900" alt="image" src="https://github.com/user-attachments/assets/55c18486-6573-41bb-a730-df7e7976c32b" />


**[日本語](#日本語) | [English](#english)**

---

## 日本語

Cube Creator X(Steam版)のマスターデータ(アイテム・食べ物・武器・レシピなど)を、GUIで編集してゲームに反映する非公式ツールです。`ccx_studio.py` 1ファイルだけで動き、`res.pac` の解析から書き戻しまで行います。

> **非公式ツールです。** 開発元・パブリッシャーとは関係ありません。自己責任でご使用ください。

### できること

- アイテム、食べ物、装備(武器・防具)、レシピ、交換、ブロックの耐久、モブ、ドロップなど、マスターデータ134表の編集
- アイテム・食べ物・装備・モブの名前と説明の編集(日本語 / English)
- 食べ物・装備を「複製して追加」すると、アイテム表(`master_item`)にも新しいアイテムを自動作成
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

### コマンドでの使い方

GUIを使わずに操作することもできます。

```
python3 ccx_studio.py info      # res.pac の解析結果を表示
python3 ccx_studio.py export    # tables/ を元データから作り直す
python3 ccx_studio.py build     # tables/ の内容を res.pac に反映
python3 ccx_studio.py restore   # マスターデータを元に戻す
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

### 仕組み

- `res.pac` は、`0x30 + n × 0x10000` の位置から始まるzlibブロックの並びで、各ブロックの直前8バイトに展開後のサイズが入っています。
- ツールは全ブロックを走査し、`system_parameter` で始まるブロックを「マスターデータ」として特定します。
- マスターデータは、表名・列(型と列名)・行数・行データが並ぶ独自の表形式です。型は整数(4バイト)、小数(float32)、1バイト値、可変長文字列、固定長文字列で、各行の末尾に4バイトの余白が付きます。
- 反映は、元データ(`res.pac.tblk`)とTSVの差分だけを書き換えて、マスターデータのブロックを同じ位置に書き込みます。他のブロックには触りません。圧縮後のサイズが元より大きい場合は、書き込まずにエラーを出します。

### 注意

- 使う前に `res.pac` のバックアップを取ることをおすすめします。
- **単独プレイ専用です。** 改変したデータでオンライン(協力・対戦)に参加しないでください。他のプレイヤーとずれたり、不正行為と見なされたりするおそれがあります。
- 既存の項目の数値や名前の変更は動作を確認しています。複製して追加した新しい項目は実験的な機能で、ゲームが新しいIDを認識するかは保証できません。
- ゲームがアップデートされて `res.pac` が変わると、ツールが検知して新しい `res.pac` を元データとして登録し直します。`tables/` は古いままなので、「TSVを元データから作り直す」を使ってください。
- 圧縮後のサイズが元の上限を超える変更は反映できません(行や文字を減らしてください)。`ccx_studio.py` 冒頭の `ALLOW_GROW = True` にすると、ページ末の余白まで使えますが、実機での動作は未検証です。
- 壊れたときは、Steamの「ファイルの整合性を確認」で元に戻せます。
- このリポジトリにゲームのデータは含まれていません。`res.pac`、書き出したTSV、音声・画像などの再配布はしないでください。

### トラブルシューティング

| 症状 | 対処 |
| --- | --- |
| `No module named tkinter` | `sudo apt install python3-tk` |
| `res.pac が見つかりません` | ツールをゲームフォルダ(`res.pac` と同じ場所)に置く |
| `表の数が合いません` など、形式のエラー | ゲームの更新で形式が変わった可能性があります。Issueで報告してください |
| `圧縮後のサイズが上限を超えました` | 追加した行や文字を減らす |

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

### Command line

You can also use it without the GUI:

```
python3 ccx_studio.py info      # show the analysis result of res.pac
python3 ccx_studio.py export    # re-create tables/ from the original data
python3 ccx_studio.py build     # apply tables/ to res.pac
python3 ccx_studio.py restore   # restore the original master data
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

### How it works

- `res.pac` is a sequence of zlib blocks starting at `0x30 + n × 0x10000`. The 8 bytes right before each block hold its decompressed size.
- The tool scans all blocks and identifies the one that begins with `system_parameter` as the master data.
- The master data is a custom table format: table name, columns (type and name), row count, then rows. Types are 4-byte integers, float32, 1-byte values, variable-length strings and fixed-length strings. Every row ends with 4 padding bytes.
- Applying changes rewrites only the differences between the original data (`res.pac.tblk`) and your TSV files, and writes the master data block back to the same position. No other block is touched. If the compressed size would exceed the original, nothing is written and an error is shown.

### Notes

- Please back up `res.pac` before using the tool.
- **Single-player use only.** Do not join online (co-op / versus) games with modified data. It may desync with other players or be treated as cheating.
- Editing existing values and names is confirmed to work. Newly duplicated entries are experimental, and there is no guarantee that the game recognizes new IDs.
- When a game update changes `res.pac`, the tool detects it and registers the new `res.pac` as the original data. `tables/` stays old, so use "TSVを元データから作り直す" (Regenerate TSV).
- Changes whose compressed size exceeds the original limit cannot be applied (reduce the added rows or text). Setting `ALLOW_GROW = True` at the top of `ccx_studio.py` allows using the padding at the end of the page, but this is untested in the real game.
- If something breaks, use Steam's "Verify integrity of game files" to restore the original.
- This repository contains no game data. Please do not redistribute `res.pac`, exported TSV files, audio or images.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No module named tkinter` | `sudo apt install python3-tk` |
| `res.pac が見つかりません` (res.pac not found) | Put the tool in the game folder, next to `res.pac` |
| Format errors such as `表の数が合いません` (table count mismatch) | The game format may have changed with an update. Please report it as an issue |
| `圧縮後のサイズが上限を超えました` (compressed size exceeds the limit) | Reduce the added rows or text |

### License

MIT License (see `LICENSE`)

"Cube Creator X" is a trademark or registered trademark of its respective owners. This tool is unofficial and is not affiliated with them.

### Credits

This tool and this README were created with Claude (Anthropic).
