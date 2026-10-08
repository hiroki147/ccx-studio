#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cube Creator X Forge(mod導入ツール)

ccx_studio.py と同じフォルダ(ゲームのフォルダ)に置いて使います。
    python3 ccx_forge.py                  GUIを起動
    python3 ccx_forge.py list             入っているmodの一覧
    python3 ccx_forge.py install a.zip..  modを追加して有効にする(反映は apply)
    python3 ccx_forge.py apply            有効なmodをゲームに反映する
    python3 ccx_forge.py restore          すべてのmodを外して、元に戻す
    python3 ccx_forge.py enable|disable|remove|purge ID
    python3 ccx_forge.py check a.zip      modの中身を確認する(ゲームは変更しません)
    python3 ccx_forge.py template [DIR]   mod作りの見本フォルダを作る
    python3 ccx_forge.py pack DIR [OUT]   フォルダをmodのzipにまとめる

modのzipには、ゲームのデータ(元の表、テキスト、画像)を入れないでください。
mod.json と、作者が自分で作った icons/*.png だけで作ります(形式は MOD_FORMAT.md を参照)。
"""
import hashlib, io, json, os, re, shutil, sys, zipfile

import ccx_studio as S

HERE = S.HERE
MODDIR = os.path.join(HERE, "mods")
FSTATE = os.path.join(HERE, "ccx_forge.json")
FORMAT = 1
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,31}$")
KEY_RE = re.compile(r"^[a-z0-9_]{1,32}$")
LIMIT_BYTES = 64 << 20


class ModError(Exception):
    pass


def need(cond, msg):
    if not cond:
        raise ModError(msg)


# ---------------------------------------------------------------- 状態
def fstate():
    try:
        with open(FSTATE, encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError):
        j = {}
    j.setdefault("order", [])
    j.setdefault("mods", {})
    j.setdefault("alloc", {})           # modごとに割り当てたID  {mod: {"item:キー": 数, ...}}
    j.setdefault("icon_slots", {})      # アイコン名 -> アトラスの範囲(使わなくなっても取っておく)
    j.setdefault("icons_applied", {})   # 今ゲームに入っているmodのアイコン  名前 -> sha1
    j.setdefault("applied", [])
    j.setdefault("conflicts", [])
    return j


def fsave(j):
    with open(FSTATE, "w", encoding="utf-8") as f:
        json.dump(j, f, indent=1, ensure_ascii=False)


# ---------------------------------------------------------------- modの読み込みと検証
def is_doc(n):
    return "/" not in n and re.match(r"(?i)^(readme|license|licence|copying|notice)[^/]*$", n) is not None


def check_ref(v, where):
    if isinstance(v, str) and v.startswith("@"):
        body = v[1:]
        need(re.match(r"^([a-z0-9][a-z0-9_]{1,31}:)?[a-z0-9_]{1,32}$", body), f"{where}: 参照 {v!r} の書き方が違います(@キー または @modのID:キー)")


def check_set(d, where):
    need(isinstance(d, dict), f"{where}: set は {{列名: 値}} の形にしてください")
    for k, v in d.items():
        need(isinstance(k, str) and k, f"{where}: 列名が不正です")
        need(isinstance(v, (int, float, str)) and not isinstance(v, bool) or isinstance(v, bool), f"{where}: {k} の値が不正です")
        check_ref(v, f"{where}.{k}")


def check_text(d, where, required):
    if d is None:
        need(not required, f"{where}: 名前(ja または en)を書いてください")
        return
    need(isinstance(d, dict) and any(isinstance(d.get(k), str) and d[k].strip() for k in ("ja", "en")),
         f"{where}: {{\"ja\": ..., \"en\": ...}} の形で、ja か en のどちらかは書いてください")
    for k, v in d.items():
        need(k in ("ja", "en", "ko", "zh_cn", "zh_tw") and isinstance(v, str), f"{where}: 言語 {k} は使えません(ja, en, ko, zh_cn, zh_tw)")


def validate(m, icons):
    need(isinstance(m, dict), "mod.json の形式が違います")
    need(m.get("format") == FORMAT, f"format は {FORMAT} にしてください")
    need(isinstance(m.get("id"), str) and ID_RE.match(m["id"]), "id は、英小文字・数字・_ だけで2〜32文字にしてください(例: ruby_pack)")
    for k in ("name", "version", "author"):
        need(isinstance(m.get(k), str) and m[k].strip(), f"{k} を書いてください")
    m.setdefault("description", "")
    m.setdefault("license", "")
    need(isinstance(m.setdefault("requires", []), list) and all(isinstance(x, str) and ID_RE.match(x) for x in m["requires"]),
         "requires は、必要なmodのIDのリストにしてください")
    keys = set()
    for n, it in enumerate(m.setdefault("items", [])):
        w = f"items[{n}]"
        need(isinstance(it, dict) and isinstance(it.get("key"), str) and KEY_RE.match(it["key"]), f"{w}: key は英小文字・数字・_ にしてください")
        need(it["key"] not in keys, f"{w}: key {it['key']} が重なっています")
        keys.add(it["key"])
        need(isinstance(it.get("copy_from"), int) and not isinstance(it["copy_from"], bool), f"{w}: copy_from(元にする、ゲームの既存アイテムのID)が必要です")
        check_text(it.get("name"), f"{w}.name", True)
        check_text(it.get("description"), f"{w}.description", False)
        if "icon" in it:
            need(it["icon"] in icons, f"{w}: icon {it['icon']!r} が zip の中にありません(icons/xxx.png)")
        need("icon" not in it or "icon_ref" not in it, f"{w}: icon と icon_ref は、どちらか片方だけにしてください")
        need("icon_ref" not in it or isinstance(it["icon_ref"], str), f"{w}: icon_ref は文字列にしてください")
        check_set(it.get("set", {}), f"{w}.set")
        for sec in ("food", "equip"):
            if sec in it:
                need(isinstance(it[sec], dict), f"{w}.{sec}: {{...}} の形にしてください")
                need("copy_from" not in it[sec] or isinstance(it[sec]["copy_from"], int), f"{w}.{sec}.copy_from は数にしてください")
                check_set(it[sec].get("set", {}), f"{w}.{sec}.set")
    rk = set()
    for n, r in enumerate(m.setdefault("recipes", [])):
        w = f"recipes[{n}]"
        need(isinstance(r, dict) and isinstance(r.get("key"), str) and KEY_RE.match(r["key"]) and r["key"] not in rk, f"{w}: key が不正か重なっています")
        rk.add(r["key"])
        need("result" in r, f"{w}: result(できあがるアイテム)が必要です")
        check_ref(r["result"], f"{w}.result")
        mats = r.get("materials", [])
        need(isinstance(mats, list) and len(mats) <= 4, f"{w}: materials は4つまでです")
        for x in mats:
            need(isinstance(x, dict) and "item" in x, f"{w}: materials は {{\"item\": ID, \"num\": 個数}} の形にしてください")
            check_ref(x["item"], f"{w}.materials")
        need(isinstance(r.get("stations", []), list) and all(isinstance(x, str) and KEY_RE.match(x) for x in r.get("stations", [])), f"{w}: stations は名前のリストにしてください")
        check_set(r.get("set", {}), f"{w}.set")
    xk = set()
    for n, r in enumerate(m.setdefault("rows", [])):
        w = f"rows[{n}]"
        need(isinstance(r, dict) and isinstance(r.get("table"), str) and isinstance(r.get("key"), str) and KEY_RE.match(r["key"]), f"{w}: table と key が必要です")
        need((r["table"], r["key"]) not in xk, f"{w}: 同じ table と key が重なっています")
        xk.add((r["table"], r["key"]))
        need(isinstance(r.get("copy_from"), (int, str)), f"{w}: copy_from(元にする行のID)が必要です")
        check_set(r.get("set", {}), f"{w}.set")
    for n, p in enumerate(m.setdefault("patches", [])):
        w = f"patches[{n}]"
        need(isinstance(p, dict) and isinstance(p.get("table"), str) and "id" in p, f"{w}: table と id が必要です")
        check_set(p.get("set", {}), f"{w}.set")
    need(not any(k not in ("format", "id", "name", "version", "author", "description", "license", "requires", "items", "recipes", "rows", "patches")
                 and not k.startswith("_") for k in m), "mod.json に、使えない項目があります")


class Mod:
    def __init__(self, path):
        self.path = path
        try:
            with zipfile.ZipFile(path) as z:
                infos = z.infolist()
                need(len(infos) <= 500 and sum(i.file_size for i in infos) <= LIMIT_BYTES, "modが大きすぎます(展開後64MBまで)")
                names = z.namelist()
                need("mod.json" in names, "mod.json がありません")
                try:
                    self.data = json.loads(z.read("mod.json").decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as e:
                    raise ModError(f"mod.json を読めません: {e}")
                self.icons = {n: z.read(n) for n in names if n.startswith("icons/") and n.lower().endswith(".png")}
                self.extra = [n for n in names if n != "mod.json" and n not in self.icons and not is_doc(n) and not n.endswith("/")]
        except zipfile.BadZipFile:
            raise ModError("zip として開けません")
        validate(self.data, self.icons)
        self.id = self.data["id"]

    def summary(self):
        d = self.data
        return (f"{d['name']} ({d['id']}) v{d['version']} / {d['author']} — アイテム {len(d['items'])}、レシピ {len(d['recipes'])}、"
                f"行追加 {len(d['rows'])}、既存の変更 {len(d['patches'])}、アイコン {sum(1 for i in d['items'] if 'icon' in i)}")


# ---------------------------------------------------------------- 型つきの表と、modの適用
class Tbl:
    def __init__(self, name, cols, rows):
        self.name, self.cols, self.rows = name, cols, [list(r) for r in rows]
        self.ix = {c: i for i, (t, c) in enumerate(cols)}

    def find(self, key):
        k = str(key)
        return next((r for r in self.rows if str(r[0]) == k), None)

    def put(self, row, col, v):
        if col not in self.ix:
            raise ModError(f"{self.name} に列 {col!r} がありません")
        t = self.cols[self.ix[col]][0]
        try:
            if t in (1, 61):
                if isinstance(v, float) and v != int(v):
                    raise ValueError("整数ではありません")
                row[self.ix[col]] = int(v)
            elif t == 12:
                row[self.ix[col]] = float(v)
            else:
                row[self.ix[col]] = str(v)
        except (ValueError, TypeError) as e:
            raise ModError(f"{self.name}.{col} に {v!r} は入れられません ({e})")

    def blank(self):
        return [0.0 if t == 12 else "" if t == 22 or t & 0xFFFF == 21 else 0 for t, _ in self.cols]


def icon_name(mod_id, key):
    return f"res_Item_ItemIcon_IMAGE_IMAGE_ICON_ICON_MOD_{mod_id.upper()}_{key.upper()}_TGA"


class Applier:
    def __init__(self, tables, fs, log):
        self.t, self.fs, self.log = tables, fs, log
        self.mod = self.mod_obj = None
        self.icons, self.touched, self.warnings = {}, {}, []
        cr, it = tables.get("master_craft"), tables["master_item"]
        self.cat_votes = {}
        if cr:
            icat = {r[0]: r[it.ix["item_category"]] for r in it.rows}
            for r in cr.rows:
                c = icat.get(r[cr.ix["result_item_id"]])
                if c is not None:
                    self.cat_votes.setdefault(c, {}).setdefault(r[cr.ix["category"]], 0)
                    self.cat_votes[c][r[cr.ix["category"]]] += 1

    # --- ID の割り当て(一度決めたIDは、modを外しても取っておく)
    def alloc(self, kind, key, chooser):
        a = self.fs["alloc"].setdefault(self.mod, {})
        k = f"{kind}:{key}"
        if k not in a:
            a[k] = chooser()
        return a[k]

    def allocated(self, kind):
        return {v for m in self.fs["alloc"].values() for k, v in m.items() if k.startswith(kind + ":")}

    def new_item_id(self, near):
        used = {int(r[0]) for r in self.t["master_item"].rows} | self.allocated("item")
        for n in ("master_item_food", "master_equip"):
            if n in self.t:
                used |= {int(r[0]) for r in self.t[n].rows}
        blk = near // 100
        top = max((x for x in used if x // 100 == blk), default=near)
        return top + 1 if top + 1 <= blk * 100 + 99 else (max(used) // 100 + 1) * 100

    def new_id(self, tbl, kind):
        return max([int(r[0]) for r in tbl.rows] + list(self.allocated(kind)) + [0]) + 1

    def resolve(self, v):
        if not (isinstance(v, str) and v.startswith("@")):
            return v
        body = v[1:]
        mod, key = body.split(":", 1) if ":" in body else (self.mod, body)
        got = self.fs["alloc"].get(mod, {}).get(f"item:{key}")
        if got is None:
            raise ModError(f"参照 {v} の相手が見つかりません" + ("(そのmodを先に有効にしてください)" if ":" in body else f"(items に key {key!r} がありません)"))
        return got

    def add_text(self, tid, tx):
        st = self.t["system_texts"]
        row = st.blank()
        ja, en = tx.get("ja") or tx.get("en"), tx.get("en") or tx.get("ja")
        for col, val in (("text_id", tid), ("text_ja", ja), ("text_en", en), ("text_ko", tx.get("ko") or en),
                         ("text_zh_cn", tx.get("zh_cn") or en), ("text_zh_tw", tx.get("zh_tw") or en)):
            if col in st.ix:
                st.put(row, col, val)
        st.rows.append(row)

    # --- 各操作
    def op_item(self, it):
        items, foods, equips = self.t["master_item"], self.t.get("master_item_food"), self.t.get("master_equip")
        src = items.find(it["copy_from"])
        if src is None:
            raise ModError(f"アイテム {it['key']}: copy_from={it['copy_from']} のアイテムが、このゲームにありません")
        nid = self.alloc("item", it["key"], lambda: self.new_item_id(int(src[0])))
        row = list(src)
        row[0] = nid
        for which, col in (("name", "name_text_id"), ("description", "description_text_id")):
            if it.get(which):
                tid = self.alloc("text", f"{it['key']}.{which}", lambda: self.new_id(self.t["system_texts"], "text"))
                self.add_text(tid, it[which])
                items.put(row, col, tid)
        if it.get("icon"):
            nm = icon_name(self.mod, it["key"])
            self.icons[nm] = (self.mod_obj.icons[it["icon"]], self.mod, it["key"])
            items.put(row, "icon_file_path", nm)
        elif it.get("icon_ref"):
            items.put(row, "icon_file_path", it["icon_ref"])
        si, ci = items.ix["sort_id"], items.ix["item_category"]
        same = [int(r[si]) for r in items.rows if r[ci] == row[ci]]
        allv = {int(r[si]) for r in items.rows}
        row[si] = max(same) + 1 if max(same) + 1 not in allv else int(src[si])
        for col, v in it.get("set", {}).items():
            items.put(row, col, self.resolve(v))
        if "equip" in it:
            if equips is None:
                raise ModError("このゲームには master_equip がありません")
            eq = it["equip"]
            base = equips.find(eq.get("copy_from", src[items.ix["equip_id"]]))
            if base is None:
                raise ModError(f"アイテム {it['key']}: 元にする装備が、このゲームにありません")
            erow = list(base)
            erow[0] = nid
            for col, v in eq.get("set", {}).items():
                equips.put(erow, col, self.resolve(v))
            equips.rows.append(erow)
            items.put(row, "equip_id", nid)
        if "food" in it:
            if foods is None:
                raise ModError("このゲームには master_item_food がありません")
            fd = it["food"]
            base = foods.find(fd.get("copy_from", src[0]))
            if base is None:
                raise ModError(f"アイテム {it['key']}: 元にする食べ物が、このゲームにありません")
            frow = list(base)
            frow[0] = nid
            for col, v in fd.get("set", {}).items():
                foods.put(frow, col, self.resolve(v))
            foods.rows.append(frow)
        items.rows.append(row)

    def op_recipe(self, r):
        cr, items = self.t.get("master_craft"), self.t["master_item"]
        if cr is None:
            raise ModError("このゲームには master_craft がありません")
        cid = self.alloc("craft", r["key"], lambda: self.new_id(cr, "craft"))
        if r.get("copy_from") is not None:
            base = cr.find(r["copy_from"])
            if base is None:
                raise ModError(f"レシピ {r['key']}: 元にするレシピ {r['copy_from']} がありません")
            row = list(base)
        else:
            row = cr.blank()
            cr.put(row, "parallel_limit", 99)
        row[0] = cid
        result = int(self.resolve(r["result"]))
        res = items.find(result)
        if res is None:
            raise ModError(f"レシピ {r['key']}: できあがるアイテム {result} が見つかりません")
        cr.put(row, "result_item_id", result)
        cr.put(row, "result_item_num", r.get("num", 1))
        cr.put(row, "name_text_id", res[items.ix["name_text_id"]])
        if r.get("copy_from") is None:
            votes = self.cat_votes.get(res[items.ix["item_category"]])
            cr.put(row, "category", max(votes, key=votes.get) if votes else max(x[cr.ix["category"]] for x in cr.rows))
        mats = r.get("materials", [])
        for i in range(1, 5):
            m = mats[i - 1] if i <= len(mats) else {"item": 0, "num": 0}
            cr.put(row, f"src_item_id{i}", self.resolve(m["item"]))
            cr.put(row, f"src_item_num{i}", m.get("num", 1) if i <= len(mats) else 0)
        if "stations" in r:
            for c in cr.ix:
                if c.startswith("enable_"):
                    cr.put(row, c, 0)
            for stn in r["stations"]:
                cr.put(row, "enable_" + stn, 1)
        cr.put(row, "sort_id", max(int(x[cr.ix["sort_id"]]) for x in cr.rows) + 1)
        for col, v in r.get("set", {}).items():
            cr.put(row, col, self.resolve(v))
        cr.rows.append(row)

    def op_row(self, r):
        t = self.t.get(r["table"])
        if t is None:
            raise ModError(f"rows: 表 {r['table']} がありません")
        if t.cols[0][0] != 1:
            raise ModError(f"rows: {t.name} は、先頭の列が整数のIDではないので、行を足せません")
        base = t.find(r["copy_from"])
        if base is None:
            raise ModError(f"rows: {t.name} に、元にする行 {r['copy_from']} がありません")
        row = list(base)
        row[0] = self.alloc(f"row:{t.name}", r["key"], lambda: self.new_id(t, f"row:{t.name}"))
        for col, v in r.get("set", {}).items():
            t.put(row, col, self.resolve(v))
        t.rows.append(row)

    def op_patch(self, p):
        t = self.t.get(p["table"])
        row = t.find(p["id"]) if t else None
        if row is None:
            self.warnings.append(f"[{self.mod}] {p['table']} の {p['id']} が、このゲームにないので、変更を飛ばしました")
            return
        for col, v in p.get("set", {}).items():
            t.put(row, col, self.resolve(v))
            self.touched.setdefault((p["table"], str(p["id"]), col), []).append(self.mod)

    def apply(self, mod):
        self.mod, self.mod_obj = mod.id, mod
        d = mod.data
        try:
            for it in d["items"]:
                self.op_item(it)
            for r in d["recipes"]:
                self.op_recipe(r)
            for r in d["rows"]:
                self.op_row(r)
            for p in d["patches"]:
                self.op_patch(p)
        except ModError as e:
            raise ModError(f"[{mod.id}] {e}")

    def conflicts(self):
        return [f"{t} の {i} の {c}: {' → '.join(ms)} (後のmodが有効)" for (t, i, c), ms in self.touched.items() if len(set(ms)) > 1]


# ---------------------------------------------------------------- 導入・管理
def load_enabled(fs):
    mods = []
    for mid in fs["order"]:
        e = fs["mods"].get(mid)
        if not e or not e.get("enabled"):
            continue
        p = os.path.join(MODDIR, e["file"])
        if not os.path.exists(p):
            raise ModError(f"mod {mid} のファイル {e['file']} が mods/ にありません")
        mods.append(Mod(p))
    ids = [m.id for m in mods]
    for m in mods:
        for r in m.data["requires"]:
            need(r in ids[:ids.index(m.id)], f"mod {m.id} は、mod {r} を先に(上の順番で)有効にする必要があります")
    return mods


def forge_install(zip_path, log=print):
    m = Mod(zip_path)
    for x in m.extra:
        log(f"注意: zip の中の {x} は使いません(mod.json と icons/*.png、README だけが使われます)")
    os.makedirs(MODDIR, exist_ok=True)
    dest = os.path.join(MODDIR, m.id + ".zip")
    if os.path.abspath(zip_path) != os.path.abspath(dest):
        shutil.copyfile(zip_path, dest)
    fs = fstate()
    upd = m.id in fs["mods"]
    fs["mods"][m.id] = dict(enabled=True, file=m.id + ".zip", name=m.data["name"], version=m.data["version"], author=m.data["author"])
    if m.id not in fs["order"]:
        fs["order"].append(m.id)
    fsave(fs)
    log(("更新しました: " if upd else "追加しました: ") + m.summary())
    return m


def forge_set(mid, **kw):
    fs = fstate()
    need(mid in fs["mods"], f"mod {mid} は入っていません")
    fs["mods"][mid].update(kw)
    fsave(fs)


def forge_move(mid, delta):
    fs = fstate()
    o = fs["order"]
    i = o.index(mid)
    j = max(0, min(len(o) - 1, i + delta))
    o.insert(j, o.pop(i))
    fsave(fs)


def forge_remove(mid, purge=False, log=print):
    fs = fstate()
    e = fs["mods"].pop(mid, None)
    need(e is not None, f"mod {mid} は入っていません")
    fs["order"] = [x for x in fs["order"] if x != mid]
    if purge:
        fs["alloc"].pop(mid, None)
    p = os.path.join(MODDIR, e["file"])
    if os.path.exists(p):
        os.remove(p)
    fsave(fs)
    log(f"mod {mid} を外しました" + ("(割り当てたIDも消しました)" if purge else "(割り当てたIDは、再導入に備えて取ってあります)")
        + "。ゲームに反映するには apply を実行してください。")


def forge_apply(log=print, dry=False):
    """有効なmodを、元のゲームのデータに順に重ねて、res.pac に書き込む"""
    fs = fstate()
    mods = load_enabled(fs)
    st = S.ensure_state(log)
    d = S.original_data(st)
    heads = S.find_heads(d)
    tables = {name: Tbl(name, cols, rows) for pos, name, cols, nr, start, end, rows in heads}
    ap = Applier(tables, fs, log)
    for m in mods:
        ap.apply(m)
    for w in ap.warnings:
        log("注意: " + w)
    conflicts = ap.conflicts()
    for c in conflicts:
        log("競合: " + c)
    nd, diffs, nchg = S.master_assemble(d, heads, {n: t.rows for n, t in tables.items()})
    log(f"有効なmod {len(mods)} 個 / 追加・変更した表 {nchg} 個 / アイコン {len(ap.icons)} 個")
    if dry:
        return conflicts
    icon_commit, placed = None, {}
    shas = {n: hashlib.sha1(v[0]).hexdigest() for n, v in ap.icons.items()}
    try:
        info, atlas = S.icon_locate(log) if (ap.icons or fs["icons_applied"]) else (None, None)
    except S.CcxError:
        info = atlas = None
    recs = S.tex_state()["blocks"]
    in_place = info is not None and str(info["block"]) in recs and str(atlas["block"]) in recs
    if ap.icons and not (shas == fs["icons_applied"] and in_place):
        Image, _e = S.need_pil()
        adds = [(n, Image.open(io.BytesIO(v[0])), tuple(fs["icon_slots"][n]) if n in fs["icon_slots"] else None) for n, v in ap.icons.items()]
        reserved = [tuple(v) for n, v in fs["icon_slots"].items() if n not in ap.icons]
        icon_commit, placed = S.icon_add_many(adds, log, orig=True, reserved=reserved)
    elif not ap.icons and fs["icons_applied"]:
        icon_commit = lambda: S.do_icon_restore(log)
    master_commit = S.master_prepare(st, d, nd, diffs, log) if nchg else (lambda: S.do_restore(log))
    if icon_commit:
        icon_commit()
    master_commit()
    for n, r in placed.items():
        fs["icon_slots"][n] = list(r)
    fs["icons_applied"] = shas
    fs["applied"] = [m.id for m in mods]
    fs["conflicts"] = conflicts
    fsave(fs)
    log(f"mod {len(mods)} 個をゲームに反映しました。")
    return conflicts


def forge_restore(log=print):
    fs = fstate()
    S.do_restore(log)
    if fs["icons_applied"]:
        S.do_icon_restore(log)
    fs["icons_applied"], fs["applied"], fs["conflicts"] = {}, [], []
    fsave(fs)
    log("すべてのmodを外して、元の状態に戻しました(modのファイルと割り当てたIDは残っています)。")


# ---------------------------------------------------------------- mod作りの補助
TEMPLATE = {
    "format": FORMAT, "id": "my_first_mod", "name": "はじめてのmod", "version": "1.0.0", "author": "あなたの名前",
    "description": "見本です。書き換えて使ってください。ゲームのデータ(テキストや画像)は入れないでください。",
    "license": "CC0-1.0", "requires": [],
    "_comment": "copy_from は、元にするゲームの既存アイテムのIDです(中身は、導入する人のゲームから読み込まれます)。",
    "items": [
        {"key": "sample_apple", "copy_from": 1200, "name": {"ja": "見本のりんご", "en": "Sample Apple"},
         "description": {"ja": "回復する見本の食べ物。", "en": "A sample food that heals."},
         "icon": "icons/sample_apple.png", "set": {"max_possession": 99}, "food": {"set": {"hp_recover": 30}}},
        {"key": "sample_sword", "copy_from": 3000, "name": {"ja": "見本の剣", "en": "Sample Sword"},
         "icon": "icons/sample_apple.png", "equip": {"set": {"damage": 12.0}}},
    ],
    "recipes": [
        {"key": "sample_apple_recipe", "result": "@sample_apple", "num": 1, "materials": [], "stations": ["empty_handed"]},
    ],
    "rows": [],
    "patches": [],
}


def forge_template(dest, log=print):
    Image, _e = S.need_pil()
    from PIL import ImageDraw
    os.makedirs(os.path.join(dest, "icons"), exist_ok=True)
    with open(os.path.join(dest, "mod.json"), "w", encoding="utf-8") as f:
        json.dump(TEMPLATE, f, indent=1, ensure_ascii=False)
    im = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((20, 24, 108, 112), fill=(210, 40, 40, 255), outline=(120, 10, 10, 255), width=4)
    ImageDraw.Draw(im).rectangle((60, 8, 68, 30), fill=(90, 60, 20, 255))
    im.save(os.path.join(dest, "icons", "sample_apple.png"))
    log(f"見本を {dest} に作りました。mod.json を書き換えて、 python3 ccx_forge.py pack {dest} でzipにします。")


def forge_pack(folder, out=None, log=print):
    p = os.path.join(folder, "mod.json")
    need(os.path.exists(p), f"{folder} に mod.json がありません")
    out = out or os.path.join(os.path.dirname(os.path.abspath(folder)), os.path.basename(os.path.abspath(folder)) + ".zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(p, "mod.json")
        for dp, dn, fn in os.walk(os.path.join(folder, "icons")):
            for x in sorted(fn):
                if x.lower().endswith(".png"):
                    z.write(os.path.join(dp, x), "icons/" + x)
        for x in sorted(os.listdir(folder)):
            if is_doc(x):
                z.write(os.path.join(folder, x), x)
    m = Mod(out)
    log(f"作りました: {out}\n  {m.summary()}")
    return out


# ---------------------------------------------------------------- 画面
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    ERR = (ModError, S.CcxError, OSError, ValueError)

    class Forge(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Cube Creator X Forge")
            self.geometry("1000x640")
            self.minsize(820, 480)
            try:
                ttk.Style().theme_use("clam")
            except tk.TclError:
                pass
            top = ttk.Frame(self)
            top.pack(fill="x", padx=6, pady=4)
            for txt, cmd in (("modを追加(zip)…", self.add), ("modsフォルダを読み込む", self.scan), ("ゲームに反映", self.apply),
                             ("すべて外して元に戻す", self.restore)):
                ttk.Button(top, text=txt, command=cmd).pack(side="left", padx=2)
            self.auto = tk.BooleanVar(value=True)
            ttk.Checkbutton(top, text="追加・変更したらすぐ反映する", variable=self.auto).pack(side="left", padx=14)
            lf = ttk.Frame(self)
            lf.pack(side="bottom", fill="x", padx=6, pady=4)
            self.logw = tk.Text(lf, height=7, state="disabled", wrap="word")
            ls = ttk.Scrollbar(lf, command=self.logw.yview)
            self.logw.configure(yscrollcommand=ls.set)
            ls.pack(side="right", fill="y")
            self.logw.pack(side="left", fill="x", expand=True)
            mid = ttk.Frame(self)
            mid.pack(fill="both", expand=True, padx=6)
            left = ttk.Frame(mid)
            left.pack(side="left", fill="both", expand=True)
            cols = ("on", "name", "id", "ver", "author", "state")
            self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
            for c, t, w in (("on", "有効", 50), ("name", "名前", 220), ("id", "ID", 130), ("ver", "版", 60), ("author", "作者", 120), ("state", "状態", 110)):
                self.tree.heading(c, text=t)
                self.tree.column(c, width=w, stretch=(c == "name"))
            self.tree.pack(fill="both", expand=True)
            self.tree.bind("<<TreeviewSelect>>", self.on_sel)
            self.tree.bind("<Double-1>", lambda e: self.toggle())
            bt = ttk.Frame(left)
            bt.pack(fill="x", pady=4)
            for txt, cmd in (("有効/無効", self.toggle), ("↑ 上へ", lambda: self.move(-1)), ("↓ 下へ", lambda: self.move(1)), ("削除…", self.remove)):
                ttk.Button(bt, text=txt, command=cmd).pack(side="left", padx=2)
            self.detail = ttk.Label(mid, width=34, wraplength=260, justify="left", anchor="nw")
            self.detail.pack(side="right", fill="y", padx=(8, 0))
            self.conf = ttk.Label(self, foreground="#a03030", wraplength=960, justify="left")
            self.conf.pack(fill="x", padx=8)
            self.refresh()

        def log(self, s):
            self.logw.config(state="normal")
            self.logw.insert("end", s + "\n")
            self.logw.see("end")
            self.logw.config(state="disabled")
            self.update_idletasks()

        def run(self, fn, *a, **kw):
            try:
                return fn(*a, **kw)
            except ERR as e:
                self.log(f"エラー: {e}")
                messagebox.showerror("できませんでした", str(e), parent=self)
                return None
            finally:
                self.refresh()

        def refresh(self):
            fs = fstate()
            sel = self.tree.selection()
            self.tree.delete(*self.tree.get_children())
            for mid in fs["order"]:
                e = fs["mods"][mid]
                state = ("反映済み" if mid in fs["applied"] else "未反映") if e["enabled"] else "無効"
                self.tree.insert("", "end", iid=mid, values=("✓" if e["enabled"] else "", e["name"], mid, e["version"], e["author"], state))
            if sel and self.tree.exists(sel[0]):
                self.tree.selection_set(sel[0])
            self.conf.config(text=("競合(同じ値を、複数のmodが変えています):\n" + "\n".join(fs["conflicts"][:6])) if fs["conflicts"] else "")
            self.on_sel()

        def on_sel(self, _=None):
            s = self.tree.selection()
            if not s:
                self.detail.config(text="modを選ぶと、中身が表示されます。\n\nmodのzipを「modを追加」で選ぶか、\nmods/ フォルダに置いて「modsフォルダを読み込む」を押してください。")
                return
            e = fstate()["mods"][s[0]]
            try:
                m = Mod(os.path.join(MODDIR, e["file"]))
                d = m.data
                txt = (f"{d['name']}\nID: {d['id']}  v{d['version']}\n作者: {d['author']}\nライセンス: {d['license'] or '(未指定)'}\n\n{d['description']}\n\n"
                       f"アイテム {len(d['items'])} / レシピ {len(d['recipes'])} / 行追加 {len(d['rows'])} / 既存の変更 {len(d['patches'])} / "
                       f"アイコン {sum(1 for i in d['items'] if 'icon' in i)}")
                if d["requires"]:
                    txt += "\n\n必要なmod: " + ", ".join(d["requires"])
                al = fstate()["alloc"].get(s[0], {})
                items = {k[5:]: v for k, v in al.items() if k.startswith("item:")}
                if items:
                    txt += "\n\n割り当てたアイテムID:\n" + "\n".join(f"  {k} = {v}" for k, v in items.items())
            except ERR as ex:
                txt = f"読み込めません: {ex}"
            self.detail.config(text=txt)

        def after_change(self):
            if self.auto.get():
                self.apply()

        def add(self):
            paths = filedialog.askopenfilenames(parent=self, title="modのzip", filetypes=[("mod (zip)", "*.zip"), ("すべて", "*.*")])
            ok = False
            for p in paths:
                ok = bool(self.run(forge_install, p, self.log)) or ok
            if ok:
                self.after_change()

        def scan(self):
            fs = fstate()
            known = {e["file"] for e in fs["mods"].values()}
            n = 0
            for fn in sorted(os.listdir(MODDIR)) if os.path.isdir(MODDIR) else []:
                if fn.lower().endswith(".zip") and fn not in known:
                    n += bool(self.run(forge_install, os.path.join(MODDIR, fn), self.log))
            self.log(f"mods/ から {n} 個のmodを読み込みました。")
            if n:
                self.after_change()

        def apply(self):
            self.log("ゲームに反映しています(アイコンがあると、数十秒かかることがあります)...")
            self.run(forge_apply, self.log)

        def restore(self):
            if messagebox.askyesno("元に戻す", "すべてのmodを外して、ゲームを元の状態に戻します。\n(modのファイルと、割り当てたIDは残ります)\n続けますか?", parent=self):
                self.run(forge_restore, self.log)

        def cur(self):
            s = self.tree.selection()
            return s[0] if s else None

        def toggle(self):
            mid = self.cur()
            if mid:
                self.run(forge_set, mid, enabled=not fstate()["mods"][mid]["enabled"])
                self.after_change()

        def move(self, d):
            mid = self.cur()
            if mid:
                self.run(forge_move, mid, d)
                self.after_change()

        def remove(self):
            mid = self.cur()
            if not mid or not messagebox.askyesno("削除", f"mod {mid} を外します。続けますか?", parent=self):
                return
            purge = messagebox.askyesno("割り当てたID", "このmodに割り当てたIDも消しますか?\n\n「いいえ」: 取っておく(同じmodを入れ直すと、同じIDになります。セーブデータの安全のため、おすすめです)\n「はい」: 消す", parent=self)
            self.run(forge_remove, mid, purge, self.log)
            self.after_change()

    Forge().mainloop()


# ---------------------------------------------------------------- コマンド
def main():
    a = sys.argv[1:]
    cmd = a[0] if a else "gui"
    try:
        if cmd == "gui":
            run_gui()
        elif cmd == "list":
            fs = fstate()
            for mid in fs["order"]:
                e = fs["mods"][mid]
                print(("[有効]" if e["enabled"] else "[無効]"), mid, e["name"], "v" + e["version"], e["author"])
            print(f"反映済み: {fs['applied']}")
        elif cmd == "install" and len(a) > 1:
            for z in a[1:]:
                forge_install(z)
        elif cmd == "apply":
            forge_apply()
        elif cmd == "restore":
            forge_restore()
        elif cmd in ("enable", "disable") and len(a) == 2:
            forge_set(a[1], enabled=(cmd == "enable"))
            print("ok(反映するには apply)")
        elif cmd == "remove" and len(a) == 2:
            forge_remove(a[1])
        elif cmd == "purge" and len(a) == 2:
            forge_remove(a[1], purge=True)
        elif cmd == "check" and len(a) == 2:
            m = Mod(a[1])
            print(m.summary())
            for x in m.extra:
                print(f"注意: {x} は使われません。ゲームのデータ(res.pac、表、テキスト、画像、音声)を配布物に入れないでください。")
            print("形式は正しいです。")
        elif cmd == "template":
            forge_template(a[1] if len(a) > 1 else os.path.join(HERE, "mod_template"))
        elif cmd == "pack" and len(a) >= 2:
            forge_pack(a[1], a[2] if len(a) > 2 else None)
        else:
            print(__doc__)
    except (ModError, S.CcxError, OSError) as e:
        print("エラー:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
