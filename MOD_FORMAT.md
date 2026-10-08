# mod の作り方と形式 / How to make a mod

**[日本語](#日本語) | [English](#english)**

---

## 日本語

Cube Creator X Forge(`ccx_forge.py`)で導入する mod は、次の中身を持つ zip です。

```
my_mod.zip
├─ mod.json          必須。mod の中身(下に説明)
├─ icons/*.png       任意。作者が自分で作ったアイコン画像
└─ README.txt など   任意。説明・ライセンス
```

**ゲームのデータ(元の表、テキスト、画像、音声、`res.pac`)は入れないでください。** mod.json は、「元にする既存のアイテムの ID」と「違う部分の値」だけを持ちます。ゲームの中身は、導入する人の手元のゲームから読み込まれます。

### 作り方(ccx_studio から書き出す)

1. `ccx_studio.py` で、アイテム・食べ物・武器・レシピなどを編集します(「複製して追加」で新しい項目を作れます)。
2. 名前と説明を、自分の言葉に変えます(元のゲームの文章のままだと、書き出しは止まります)。
3. 絵を付けるときは、「アイコン…」で、自分で作った画像を追加して、アイテムの `icon_file_path` に設定します。
4. 「modとして書き出す(zip)…」を押して、ID・名前・作者・ライセンスを入れて書き出します。

### 作り方(手で書く)

```
python3 ccx_forge.py template my_mod     # 見本のフォルダを作る
(my_mod/mod.json と icons/ を書き換える)
python3 ccx_forge.py pack my_mod         # zip にまとめる(中身も検査します)
python3 ccx_forge.py check my_mod.zip    # 形式の確認
```

### mod.json

| 項目 | 内容 |
| --- | --- |
| `format` | `1` |
| `id` | mod の ID。英小文字・数字・`_` で2〜32文字。他の mod と重ならない名前にする |
| `name` / `version` / `author` | 名前・版・作者(必須) |
| `description` / `license` | 説明・ライセンス(例: `CC0-1.0`、`CC-BY-4.0`) |
| `requires` | 必要な mod の ID のリスト(その mod を、上の順番で先に有効にする必要があります) |
| `items` | 新しいアイテム(食べ物・武器を含む) |
| `recipes` | 新しいレシピ |
| `rows` | ほかの表に行を足す(例: `master_exchange`) |
| `patches` | 既存の行の値を変える |

`_` で始まる項目は、メモとして使えます(無視されます)。

### items

```json
{
  "key": "ruby_apple",
  "copy_from": 1200,
  "name": {"ja": "ルビーりんご", "en": "Ruby Apple"},
  "description": {"ja": "...", "en": "..."},
  "icon": "icons/ruby_apple.png",
  "set": {"max_possession": 99},
  "food": {"set": {"hp_recover": 30}},
  "equip": {"copy_from": 3000, "set": {"damage": 12.0}}
}
```

- `key`: mod の中で、このアイテムを呼ぶ名前(英小文字・数字・`_`)。ほかの項目から `"@ruby_apple"` で参照できます。
- `copy_from`: 元にする、ゲームの既存アイテムの ID(必須)。性質(分類・重さ・所持上限など)はここからコピーされます。
- `name`: 名前(`ja` か `en` のどちらかは必須。`ko`、`zh_cn`、`zh_tw` も書けます。無い言語は `en` が使われます)。
- `description`: 説明(任意。無いときは、元にしたアイテムの説明が使われます)。
- `icon`: zip の中の PNG(任意)。導入時に、アイコンの画像の空きに入れて、名前を自動で付けます。
- `icon_ref`: 既存のアイコンの名前を使う場合(`icon` とは、どちらか片方だけ)。
- `set`: `master_item` の列を上書きします(例: `max_possession`、`weight`)。
- `food`: 食べ物にする場合。`master_item_food` の行を、元の食べ物(`copy_from` を省略すると、元のアイテムの食べ物)からコピーして、`set` で上書きします。
- `equip`: 武器・防具にする場合。`master_equip` の行を、元の装備からコピーして、`set` で上書きします。

### recipes

```json
{
  "key": "ruby_apple_recipe",
  "result": "@ruby_apple",
  "num": 1,
  "materials": [{"item": 1030, "num": 2}, {"item": "@ruby_gem", "num": 1}],
  "stations": ["empty_handed"],
  "set": {"category": 2}
}
```

- `result`: できあがるアイテム(ID または `@キー`)。
- `materials`: 材料(最大4つ)。`item` は ID、`@キー`、または別の mod のアイテム `@modのID:キー`。
- `stations`: 作れる場所。`empty_handed`(素手)、`workbench`(作業台)など、`master_craft` の `enable_` に続く名前。
- `set`: `master_craft` の列の上書き(`category`、`craft_time_base` など)。

### rows / patches

```json
{"table": "master_exchange", "key": "x1", "copy_from": 101, "set": {"result_item_id": "@ruby_apple"}}
{"table": "master_item", "id": 1200, "set": {"max_possession": 77}}
```

`rows` は、表の先頭の列が整数の ID である表に、行を足します(ID は自動で割り当てます)。`patches` は、既存の行の、変えたい列の値だけを書きます。

### ID・テキスト・アイコンが重ならない仕組み

- mod の中では、アイテムを `key` で呼びます。導入するときに、Forge が、アイテムの ID、テキストの ID、レシピの ID、アイコンの場所を、空いているところに自動で割り当てます。
- 一度割り当てた ID は、`ccx_forge.json` に保存されます。ほかの mod を入れたり外したりしても、同じ mod には同じ ID が付きます(セーブデータが壊れにくくなります)。
- 同じ値(例: ID 1200 の最大所持数)を、複数の mod が `patches` で変えると「競合」として表示されます。上の順番にある mod のあとに、下の mod が重なります(後のものが有効です)。

### 配布のルール(著作権)

- zip に入れてよいのは、`mod.json`、自分で作ったアイコン、README やライセンスの文章です。
- 入れてはいけないもの: `res.pac`、`ccx_studio.py` で書き出した表(`tables/`)、ゲームのテキスト、ゲームから取り出した画像・音声、ゲームの画像を加工した画像。
- 名前・説明・アイコンは、自分で作ったものにしてください。元のゲームの文章と同じものは、ツールが書き出しを止めます。
- ゲームのアイコンを差し替えたものは、書き出されません(ゲームの画像から作った物は配布できません)。
- 配布するときは、`license` に、あなたが決めた条件を書いてください。

---

## English

A mod for Cube Creator X Forge (`ccx_forge.py`) is a zip with this layout:

```
my_mod.zip
├─ mod.json          required: the mod's contents (below)
├─ icons/*.png       optional: icon images made by the author
└─ README.txt etc.   optional: description / license
```

**Do not include any game data (original tables, text, images, audio, `res.pac`).** `mod.json` holds only "the ID of an existing item to base it on" and "the values that differ". The game's contents are read from the installer's own copy of the game.

### Making a mod

- From ccx_studio: edit items, foods, weapons and recipes ("複製して追加" creates new entries), rewrite names and descriptions in your own words (export stops if they are still the game's text), add your own icon images with "アイコン…", then press "modとして書き出す(zip)…".
- By hand: `python3 ccx_forge.py template my_mod`, edit `my_mod/mod.json` and `icons/`, then `python3 ccx_forge.py pack my_mod` and `python3 ccx_forge.py check my_mod.zip`.

### mod.json

Required: `format` (`1`), `id` (lowercase letters, digits, `_`; 2-32 chars), `name`, `version`, `author`. Optional: `description`, `license`, `requires` (IDs of mods that must be enabled above this one), and the lists `items`, `recipes`, `rows`, `patches`. Keys starting with `_` are ignored (use them for notes).

- `items[]`: `key`, `copy_from` (ID of an existing game item to copy properties from), `name` / `description` (`ja`, `en`, optionally `ko`, `zh_cn`, `zh_tw`), `icon` (a PNG in the zip) or `icon_ref` (an existing icon name), `set` (columns of `master_item`), `food` (`master_item_food` row: `copy_from`, `set`), `equip` (`master_equip` row: `copy_from`, `set`). Other entries can refer to the item as `"@key"`; other mods can use `"@modid:key"`.
- `recipes[]`: `key`, `result`, `num`, `materials` (up to 4: `item`, `num`), `stations` (such as `empty_handed`, `workbench`: the names after `enable_` in `master_craft`), `set`.
- `rows[]`: `table`, `key`, `copy_from` (row ID), `set`: adds a row to a table whose first column is an integer ID.
- `patches[]`: `table`, `id`, `set`: changes only the listed columns of an existing row.

### How IDs, texts and icons avoid collisions

Forge assigns item IDs, text IDs, recipe IDs and icon positions at install time and remembers them in `ccx_forge.json`, so the same mod keeps the same IDs when other mods are added or removed. When several mods change the same value via `patches`, it is shown as a conflict, and the mod lower in the list wins.

### Distribution rules

Put in the zip only `mod.json`, icons you made yourself, and README/license text. Never include `res.pac`, the exported `tables/`, the game's text, images or audio extracted from the game, or edited versions of the game's images. Choose a `license` for your mod.
