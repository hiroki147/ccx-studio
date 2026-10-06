#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cube Creator X Studio(単体版)

ゲームのフォルダ(res.pac がある場所)に置いて起動するだけで使えます。
    python3 ccx_studio.py            GUIを起動(初回は res.pac を自動解析して tables/ を作ります)
    python3 ccx_studio.py info       res.pac の解析結果を表示
    python3 ccx_studio.py export     tables/ を res.pac の元データから作り直す
    python3 ccx_studio.py build      tables/ の内容を res.pac に反映
    python3 ccx_studio.py restore    res.pac のマスターデータを元に戻す
Linuxでtkinterが無い場合: sudo apt install python3-tk
"""
import csv, hashlib, json, mmap, os, re, shutil, struct, sys, zlib
import tkinter as tk
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
TDIR = os.path.join(HERE, "tables")
ENC = dict(encoding="utf-8", errors="surrogateescape", newline="")

PAC = os.path.join(HERE, "res.pac")
ORIG = PAC + ".orig"    # 旧 cctool.py が作ったバックアップ(あれば元データの取得元に使う)
BACKUP = PAC + ".tblk"  # マスターデータ部分の元データ(このツールが作る。数百KB)
STATE = os.path.join(HERE, "ccx_state.json")
BLOCKS = os.path.join(HERE, "blocks.csv")
PAGE, HDR = 0x10000, 0x30
ALLOW_GROW = False  # True: 圧縮後が元より大きくても、ページ末の余白まで使う(未検証)
IDENT = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")


class CcxError(Exception):
    pass


# ---------------------------------------------------------------- res.pac の解析
def sha1(b):
    return hashlib.sha1(b).hexdigest()


def scan(path, log=print):
    """res.pac を先頭から走査し、zlibブロックの (開始位置, 圧縮サイズ, 展開サイズ, 先頭64バイト) を返す。
    ブロックは 0x30 + n*0x10000 の位置から始まり、直前の8バイトに展開後サイズが入っている。"""
    size = os.path.getsize(path)
    blocks, pos = [], HDR
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        while pos + 2 <= size:
            b0, b1 = mm[pos], mm[pos + 1]
            if b0 == 0x78 and ((b0 << 8) | b1) % 31 == 0:
                d, n, got, head, ok = zlib.decompressobj(), 0, 0, b"", False
                try:
                    while pos + got < size:
                        chunk = mm[pos + got:pos + got + (256 << 10)]
                        o = d.decompress(chunk)
                        if len(head) < 64:
                            head = (head + o)[:64]
                        n += len(o)
                        got += len(chunk)
                        if d.eof:
                            ok = True
                            break
                except zlib.error:
                    ok = False
                if ok:
                    comp = got - len(d.unused_data)
                    blocks.append((pos, comp, n, head))
                    pos = HDR + -(-(pos + comp - HDR) // PAGE) * PAGE
                    if len(blocks) % 1000 == 0:
                        log(f"  {len(blocks)} ブロック...")
                    continue
            pos += PAGE
    return blocks


def write_blocks_csv(blocks):
    with open(BLOCKS, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "offset", "comp", "decomp", "gap"])
        prev = HDR
        for i, (off, comp, dec, _h) in enumerate(blocks):
            w.writerow([i, off, comp, dec, off - prev])
            prev = off + comp


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_state(st):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


def read_region(path, off, comp):
    with open(path, "rb") as f:
        f.seek(off - 8)
        return f.read(comp + 8)


def init_state(log=print):
    """res.pac を解析し、マスターデータのブロックを見つけて元データを保存する"""
    if not os.path.exists(PAC):
        raise CcxError("res.pac が見つかりません。このファイルを res.pac があるフォルダ(ゲームのフォルダ)に置いてください。")
    size = os.path.getsize(PAC)
    src = ORIG if os.path.exists(ORIG) and os.path.getsize(ORIG) == size else PAC
    log(f"{os.path.basename(src)} を解析しています(初回のみ。数秒かかります)...")
    blocks = scan(src, log)
    if not blocks:
        raise CcxError("zlibブロックが見つかりません。res.pac が想定と違う形式です。")
    t = next((i for i, b in enumerate(blocks) if b[3][4:24] == b"\x10\x00\x00\x00system_parameter"), None)
    if t is None:
        raise CcxError("マスターデータ(system_parameter)のブロックが見つかりません。")
    write_blocks_csv(blocks)
    off, comp, dec, _h = blocks[t]
    room = -(-(off + comp - HDR) // PAGE) * PAGE - off
    orig, cur = read_region(src, off, comp), read_region(PAC, off, comp)
    try:
        zlib.decompress(orig[8:])
    except zlib.error as e:
        raise CcxError(f"マスターデータを展開できません: {e}")
    with open(BACKUP, "wb") as f:
        f.write(orig)
    st = dict(version=1, off=off, comp=comp, decomp=dec, room=room, size=size, block=t,
              nblocks=len(blocks), orig_sha1=sha1(orig), mod_sha1=(sha1(cur) if cur != orig else None))
    save_state(st)
    log(f"ブロック数 {len(blocks)} / マスターデータはブロック {t} (位置 0x{off:x}, 圧縮 {comp} バイト, 展開 {dec} バイト)")
    return st


def ensure_state(log=print):
    st = load_state()
    if st and os.path.exists(BACKUP) and os.path.exists(PAC) and os.path.getsize(PAC) == st["size"]:
        cur = sha1(read_region(PAC, st["off"], st["comp"]))
        with open(BACKUP, "rb") as f:
            ok = sha1(f.read()) == st["orig_sha1"]
        if ok and cur in (st["orig_sha1"], st.get("mod_sha1")):
            return st
        log("res.pac が更新されたか、別のファイルに変わっています。新しい res.pac を元データとして登録し直します。")
    return init_state(log)


def original_data(st):
    with open(BACKUP, "rb") as f:
        return zlib.decompress(f.read()[8:])


# ---------------------------------------------------------------- マスターデータの表
def parse_header(d, pos):
    try:
        L = struct.unpack_from("<I", d, pos)[0]
        if not 3 <= L <= 64:
            return None
        name = d[pos + 4:pos + 4 + L]
        if not IDENT.fullmatch(name):
            return None
        p = pos + 4 + L
        nc = struct.unpack_from("<I", d, p)[0]
        p += 4
        if not 1 <= nc <= 128:
            return None
        cols = []
        for _ in range(nc):
            t, cl = struct.unpack_from("<II", d, p)
            p += 8
            if not 1 <= cl <= 64:
                return None
            cn = d[p:p + cl]
            if not IDENT.fullmatch(cn):
                return None
            p += cl
            cols.append((t, cn.decode()))
        nr = struct.unpack_from("<I", d, p)[0]
        return pos, name.decode(), cols, nr, p + 4
    except struct.error:
        return None


def read_row(d, p, cols):
    v = []
    for t, _ in cols:
        if t == 1:
            v.append(struct.unpack_from("<i", d, p)[0]); p += 4
        elif t == 12:
            v.append(struct.unpack_from("<f", d, p)[0]); p += 4
        elif t == 61:
            v.append(d[p]); p += 1
        elif t == 22:
            n = struct.unpack_from("<I", d, p)[0]; p += 4
            v.append(d[p:p + n].decode("utf-8", "surrogateescape")); p += n
        elif t & 0xFFFF == 21:
            n = (t >> 16) + 1
            v.append(d[p:p + n].split(b"\0")[0].decode("utf-8", "surrogateescape")); p += n
        else:
            raise ValueError(f"unknown type {t}")
    return v, p + 4


def find_heads(d):
    """先頭から表を順に読む。戻り値: [(見出しの位置, 表名, 列, 行数, 行データの開始, 終了, 行のリスト)]"""
    n = struct.unpack_from("<I", d, 0)[0]
    heads, pos = [], 4
    for _ in range(n):
        h = parse_header(d, pos)
        if h is None:
            raise CcxError(f"表の見出しを読めません(位置 {pos})。ゲームのデータ形式が変わった可能性があります。")
        _p, name, cols, nr, start = h
        p, rows = start, []
        try:
            for _r in range(nr):
                v, p = read_row(d, p, cols)
                rows.append(v)
        except (struct.error, ValueError, IndexError) as e:
            raise CcxError(f"表 {name} の行を読めません: {e}")
        heads.append((pos, name, cols, nr, start, p, rows))
        pos = p
    return heads


def pack_row(cols, vals):
    o = b""
    for (t, c), x in zip(cols, vals):
        if t == 1:
            o += struct.pack("<i", int(x))
        elif t == 12:
            o += struct.pack("<f", float(x))
        elif t == 61:
            o += bytes([int(x)])
        else:
            b = str(x).encode("utf-8", "surrogateescape")
            if t == 22:
                o += struct.pack("<I", len(b)) + b
            else:
                n = (t >> 16) + 1
                if len(b) > n:
                    raise ValueError(f"{c}: 文字列が長すぎます({len(b)} > {n}バイト)")
                o += b.ljust(n, b"\0")
    return o + b"\0\0\0\0"


def conv(t, s):
    if t in (1, 61):
        return int(s)
    if t == 12:
        return float(s)
    return s


def read_tsv(path, cols):
    with open(path, **ENC) as f:
        r = csv.reader(f, delimiter="\t")
        if next(r) != [c for _, c in cols]:
            raise ValueError("列名が変わっています")
        rows = []
        for row in r:
            if not row:
                continue
            if len(row) != len(cols):
                raise ValueError(f"列数が違う行があります {row[:3]}")
            rows.append([conv(t, s) for (t, _), s in zip(cols, row)])
        return rows


# ---------------------------------------------------------------- 操作(GUIからもコマンドからも使う)
def do_export(log=print):
    """res.pac のマスターデータを tables/*.tsv に書き出す(既存のTSVは上書き)"""
    st = ensure_state(log)
    d = original_data(st)
    heads = find_heads(d)
    os.makedirs(TDIR, exist_ok=True)
    ok = 0
    for pos, name, cols, nr, start, end, rows in heads:
        with open(os.path.join(TDIR, name + ".tsv"), "w", **ENC) as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow([c for _, c in cols])
            w.writerows(rows)
        ok += 1
    log(f"tables/ に {ok} 個のTSVを書き出しました")


def do_build(log=print):
    """tables/*.tsv の変更を res.pac に反映する(元データからの差分だけを書き込む)"""
    st = ensure_state(log)
    if not os.path.isdir(TDIR):
        raise CcxError("tables/ がありません。先に export を実行してください。")
    d = original_data(st)
    heads = find_heads(d)
    out, diffs, nchg = [d[:heads[0][0]]], [], 0
    for pos, name, cols, nr, start, end, old in heads:
        path = os.path.join(TDIR, name + ".tsv")
        if not os.path.exists(path):
            out.append(d[pos:end])
            continue
        try:
            new = read_tsv(path, cols)
        except ValueError as e:
            raise CcxError(f"{name}.tsv: {e}")
        if new == old:
            out.append(d[pos:end])
            continue
        nchg += 1
        if len(new) != len(old):
            diffs.append(f"{name}: 行数 {len(old)} -> {len(new)}")
        else:
            for i, (a, b) in enumerate(zip(old, new)):
                for (t, c), x, y in zip(cols, a, b):
                    if x != y:
                        diffs.append(f"{name} 行{i} {c}: {x!r} -> {y!r}")
        try:
            body = b"".join(pack_row(cols, r) for r in new)
        except (ValueError, struct.error, OverflowError) as e:
            raise CcxError(f"{name}: 値が範囲外です ({e})")
        out.append(d[pos:start - 4] + struct.pack("<I", len(new)) + body)
    out.append(d[heads[-1][5]:])
    if nchg == 0:
        log("変更がありません。マスターデータを元の状態にします。")
        do_restore(log)
        return
    log("\n".join(diffs[:60]) + (f"\n... 他 {len(diffs) - 60} 件" if len(diffs) > 60 else ""))
    nd = b"".join(out)
    z = zlib.compress(nd, 9)
    limit = st["room"] if ALLOW_GROW else st["comp"]
    log(f"マスターデータ: {len(d)} -> {len(nd)} バイト / 圧縮後 元={st['comp']} 今回={len(z)} 上限={limit}")
    if len(z) > limit:
        raise CcxError("圧縮後のサイズが上限を超えました。res.pac は変更していません。"
                       "追加した行や文字を減らしてください。")
    off, comp = st["off"], st["comp"]
    with open(PAC, "r+b") as f:
        f.seek(off - 8)
        f.write(struct.pack("<Q", len(nd)))
        f.write(z + b"\0" * max(comp - len(z), 0))
    st["mod_sha1"] = sha1(read_region(PAC, off, comp))
    st["grown"] = len(z) if len(z) > comp else 0
    save_state(st)
    log("res.pac に反映しました。")


def do_restore(log=print):
    """res.pac のマスターデータを元の状態に戻す"""
    st = ensure_state(log)
    off, comp = st["off"], st["comp"]
    with open(BACKUP, "rb") as f:
        orig = f.read()
    with open(PAC, "r+b") as f:
        f.seek(off - 8)
        f.write(orig)
        if st.get("grown", 0) > comp:
            f.write(b"\0" * (st["grown"] - comp))
    st["mod_sha1"], st["grown"] = None, 0
    save_state(st)
    log("res.pac のマスターデータを元に戻しました。")


def do_info(log=print):
    st = ensure_state(log)
    heads = find_heads(original_data(st))
    log(f"res.pac: {st['size']} バイト / ブロック数 {st['nblocks']} / マスターデータ: ブロック {st['block']}, "
        f"表 {len(heads)} 個, 状態: {'変更済み' if st.get('mod_sha1') else '元のまま'}")



LABELS = {
    "item_id": "アイテムID", "name_text_id": "名前のテキストID", "description_text_id": "説明のテキストID",
    "sort_id": "並び順", "max_possession": "所持上限", "max_durability": "最大耐久", "weight": "重さ",
    "item_category": "カテゴリ", "creative_category": "クリエイティブ分類", "stage_category": "ステージ分類",
    "equip_id": "装備ID", "action_id": "アクションID", "icon_file_path": "アイコン画像",
    "hp_recover": "HP回復", "hungry_recover": "空腹回復", "heat_recover": "暑さ回復",
    "cold_recover": "寒さ回復", "air_recover": "空気回復", "sleep_recover": "睡眠回復",
    "buff_id": "バフID", "buff_seconds": "バフ時間(秒)", "buff_rate": "バフ確率", "buff_lv": "バフLv",
    "damage": "ダメージ", "critical_rate": "クリティカル率", "defense_rate": "防御率",
    "damage_rate_dirt": "ダメージ倍率:土", "damage_rate_wood": "ダメージ倍率:木",
    "damage_rate_leaf": "ダメージ倍率:葉", "damage_rate_stone": "ダメージ倍率:石",
    "aim_distance": "射程", "fire_speed": "発射速度", "equip_category": "装備カテゴリ",
    "result_item_id": "完成品のID", "result_item_num": "完成品の個数", "craft_time_base": "基本の作成時間",
    "max_hp": "最大HP(耐久)", "is_enemy": "敵かどうか", "drop_rate": "ドロップ率", "npc_id": "NPCのID",
    "cube_id": "ブロックID", "text_id": "テキストID", "text_ja": "日本語", "text_en": "English",
    "damage_color_r": "破片の色R", "damage_color_g": "破片の色G", "damage_color_b": "破片の色B",
    "damage_type": "ダメージ種別", "ignore_explosion": "爆発無効", "parameter_value": "値",
    "parameter_id": "パラメータID", "setting_id": "設定ID",
}
TOOLS = {"hand": "素手", "harpoon": "ハープーン", "shovel": "ショベル", "ax": "おの",
         "pickax": "つるはし", "sword": "剣", "bow": "弓", "cane": "杖"}


def label(col):
    if col in LABELS:
        return f"{LABELS[col]} ({col})"
    m = re.fullmatch(r"src_item_(id|num)(\d)", col)
    if m:
        return f"材料{m.group(2)}の{'ID' if m.group(1) == 'id' else '個数'} ({col})"
    m = re.fullmatch(r"ignore_damage_(\w+)", col)
    if m and m.group(1) in TOOLS:
        return f"無効:{TOOLS[m.group(1)]} ({col})"
    if col.startswith("enable_"):
        return f"使える場所:{col[7:]} ({col})"
    return col


def short(s):
    """float32由来の長い小数(0.10000000149011612)を 0.1 のように短く表示する"""
    try:
        x = float(s)
        if x != x or x in (float("inf"), float("-inf")):
            return s
        for p in range(1, 10):
            t = f"{x:.{p}g}"
            if struct.unpack("<f", struct.pack("<f", float(t)))[0] == x:
                if "e" in t and 1e-4 <= abs(x) < 1e15:
                    t = repr(float(t))
                elif "e" not in t and "." not in t:
                    t += ".0"
                return t
    except (ValueError, OverflowError, struct.error):
        pass
    return s


def ref_kind(col):
    if "item_id" in col:
        return "item"
    if col == "npc_id" or col.endswith("_npc_id"):
        return "npc"
    if "cube_id" in col:
        return "cube"
    if col == "equip_id":
        return "equip"
    if col.endswith("text_id"):
        return "text"
    return None


CFG = {
    "master_item": dict(title="アイテム", name=("text", "name_text_id"),
                        texts=[("name_text_id", "名前"), ("description_text_id", "説明")],
                        show=["max_possession", "max_durability", "weight", "item_category"]),
    "master_item_food": dict(title="食べ物", show=["hp_recover", "hungry_recover", "buff_seconds"]),
    "master_equip": dict(title="装備(武器・防具)", show=["equip_category", "damage", "defense_rate", "critical_rate"]),
    "master_craft": dict(title="レシピ", name=("item", "result_item_id"), extra=("材料", "materials"),
                         show=["result_item_num", "craft_time_base"]),
    "master_exchange": dict(title="交換", name=("item", "result_item_id"), extra=("材料", "materials"),
                            show=["result_item_num"]),
    "master_cube_damage": dict(title="ブロックの耐久", show=["max_hp", "damage_type"]),
    "master_npc": dict(title="モブ・NPC", name=("text", "name_text_id"),
                       texts=[("name_text_id", "名前"), ("description_text_id", "説明")],
                       show=["max_hp", "is_enemy"]),
    "master_npc_drop_item": dict(title="モブのドロップ", show=["setting_id", "drop_rate"]),
    "master_npc_battle": dict(title="モブの戦闘"),
    "master_npc_move": dict(title="モブの移動"),
    "master_treasure_contents": dict(title="宝箱の中身"),
    "system_texts": dict(title="テキスト(全言語)", show=["text_en"]),
    "system_parameter": dict(title="システム定数"),
}
AUTO = {"item_id": ("item", "item_id"), "npc_id": ("npc", "npc_id"), "cube_id": ("cube", "cube_id"),
        "equip_id": ("equip", "equip_id"), "text_id": ("text", "text_id")}


class Table:
    def __init__(self, name):
        self.name = name
        self.path = os.path.join(TDIR, name + ".tsv")
        with open(self.path, **ENC) as f:
            r = list(csv.reader(f, delimiter="\t"))
        self.cols = r[0]
        self.rows = [x for x in r[1:] if x]
        self.dirty = False
        self.kinds = [self._kind(i) for i in range(len(self.cols))]

    def _kind(self, i):
        vals = [r[i] for r in self.rows if len(r) > i]
        if not vals:
            return "str"
        for k, fn in (("int", int), ("float", float)):
            try:
                for v in vals:
                    fn(v)
                return k
            except ValueError:
                pass
        return "str"

    def check(self, i, v):
        k = self.kinds[i]
        if k == "int":
            return str(int(v.strip()))
        if k == "float":
            float(v.strip())
            return v.strip()
        return v

    def save(self):
        with open(self.path, "w", **ENC) as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow(self.cols)
            w.writerows(self.rows)
        self.dirty = False


class Data:
    def __init__(self):
        self.t = {fn[:-4]: Table(fn[:-4]) for fn in sorted(os.listdir(TDIR)) if fn.endswith(".tsv")}
        for need in ("system_texts", "master_item"):
            if need not in self.t:
                raise SystemExit(f"tables/{need}.tsv がありません。先に cctool.py export を実行してください。")
        self.reindex()

    def reindex(self):
        st, it = self.t["system_texts"], self.t["master_item"]
        self.ja, self.en = st.cols.index("text_ja"), st.cols.index("text_en")
        self.text_row = {r[0]: r for r in st.rows}
        self.i_name, i_eq = it.cols.index("name_text_id"), it.cols.index("equip_id")
        self.item_row = {r[0]: r for r in it.rows}
        self.equip_item = {}
        for r in it.rows:
            self.equip_item.setdefault(r[i_eq], r[0])
        npc = self.t.get("master_npc")
        self.npc_row = {r[0]: r for r in npc.rows} if npc else {}
        self.npc_i = npc.cols.index("name_text_id") if npc else 0
        ic = self.t.get("master_item_cube")
        self.cube_item = {r[1]: r[0] for r in ic.rows} if ic else {}

    def text(self, tid):
        r = self.text_row.get(tid)
        return r[self.ja].replace("\n", " ") if r else ""

    def item_name(self, iid):
        r = self.item_row.get(iid)
        return self.text(r[self.i_name]) if r else ""

    def npc_name(self, nid):
        r = self.npc_row.get(nid)
        return self.text(r[self.npc_i]) if r else ""

    def cube_name(self, cid):
        return self.item_name(self.cube_item.get(cid, ""))

    def equip_name(self, eid):
        return self.item_name(self.equip_item.get(eid, "")) if eid != "0" else ""

    def lookup(self, kind, v):
        return {"item": self.item_name, "npc": self.npc_name, "cube": self.cube_name,
                "equip": self.equip_name, "text": self.text}[kind](v)

    def choices(self, kind):
        if kind == "item":
            return [(i, self.item_name(i)) for i in self.item_row]
        if kind == "npc":
            return [(i, self.npc_name(i)) for i in self.npc_row]
        if kind == "cube":
            return [(c, self.cube_name(c)) for c in self.cube_item]
        if kind == "equip":
            return [(e, self.equip_name(e)) for e in self.equip_item if e != "0"]
        return []

    def new_text_id(self):
        return str(max(int(k) for k in self.text_row if k.lstrip("-").isdigit()) + 1)

    def materials(self, tb, row):
        out = []
        for i, c in enumerate(tb.cols):
            m = re.fullmatch(r"src_item_id(\d)", c)
            if m and row[i] != "0" and ("src_item_num" + m.group(1)) in tb.cols:
                n = row[tb.cols.index("src_item_num" + m.group(1))]
                out.append(f"{self.item_name(row[i]) or row[i]}×{n}")
        return " + ".join(out)

    def row_name(self, tb, row):
        if tb.name == "master_npc_drop_item":
            return f"{self.npc_name(row[0])} → {self.item_name(row[2])}"
        rule = CFG.get(tb.name, {}).get("name") or AUTO.get(tb.cols[0])
        if not rule:
            return ""
        return self.lookup(rule[0], row[tb.cols.index(rule[1])])


class Scroll(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.cv = tk.Canvas(self, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.cv.yview)
        self.inner = ttk.Frame(self.cv)
        self.inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.win = self.cv.create_window((0, 0), window=self.inner, anchor="nw")
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self.win, width=e.width))
        self.cv.configure(yscrollcommand=sb.set)
        self.cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(ev, self._wheel, add="+")

    def _wheel(self, e):
        w = self.winfo_containing(e.x_root, e.y_root)
        if w is None or not str(w).startswith(str(self)) or isinstance(w, tk.Text):
            return
        self.cv.yview_scroll(-1 if (e.num == 4 or e.delta > 0) else 1, "units")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cube Creator X Studio")
        self.geometry("1240x700")
        self.minsize(980, 560)
        try:
            ttk.Style().theme_use("clam")
        except tk.TclError:
            pass
        self.data = Data()
        self.cur = None
        self.ri = None
        self.fields, self.textw = [], []
        self._lock = False
        self._ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.fill_tables()

    # ---------- 画面 ----------
    def _ui(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=6, pady=4)
        for txt, cmd in (("TSVを保存", self.save_all), ("ゲームに反映", self.build),
                         ("ゲームを元に戻す", self.restore), ("TSVを読み直す", self.reload),
                         ("TSVを元データから作り直す", self.regen)):
            ttk.Button(bar, text=txt, command=cmd).pack(side="left", padx=2)
        self.status = ttk.Label(bar, text="")
        self.status.pack(side="right")

        lf = ttk.Frame(self)
        lf.pack(side="bottom", fill="x", padx=6, pady=4)
        self.logw = tk.Text(lf, height=6, state="disabled", wrap="word")
        ls = ttk.Scrollbar(lf, command=self.logw.yview)
        self.logw.configure(yscrollcommand=ls.set)
        ls.pack(side="right", fill="y")
        self.logw.pack(side="left", fill="x", expand=True)

        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=6)
        self.pw = pw
        self.after(150, self.set_sashes)
        left = ttk.Frame(pw)
        pw.add(left, weight=0)
        self.tlist = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tlist.column("#0", width=160)
        s1 = ttk.Scrollbar(left, command=self.tlist.yview)
        self.tlist.configure(yscrollcommand=s1.set)
        s1.pack(side="right", fill="y")
        self.tlist.pack(side="left", fill="both", expand=True)

        mid = ttk.Frame(pw)
        pw.add(mid, weight=3)
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *a: None if self._lock else self.fill_rows())
        row = ttk.Frame(mid)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="検索:").pack(side="left")
        ttk.Entry(row, textvariable=self.q).pack(side="left", fill="x", expand=True, padx=4)
        self.rtree = ttk.Treeview(mid, show="headings", selectmode="browse")
        s2 = ttk.Scrollbar(mid, command=self.rtree.yview)
        s3 = ttk.Scrollbar(mid, orient="horizontal", command=self.rtree.xview)
        self.rtree.configure(yscrollcommand=s2.set, xscrollcommand=s3.set)
        s3.pack(side="bottom", fill="x")
        s2.pack(side="right", fill="y")
        self.rtree.pack(side="left", fill="both", expand=True)
        self.rtree.bind("<<TreeviewSelect>>", self.on_row)

        right = ttk.Frame(pw)
        pw.add(right, weight=3)
        bt = ttk.Frame(right)
        bt.pack(fill="x", pady=2)
        ttk.Button(bt, text="適用", command=self.apply).pack(side="left", padx=2)
        ttk.Button(bt, text="複製して追加", command=self.dup).pack(side="left", padx=2)
        ttk.Button(bt, text="削除", command=self.delete).pack(side="left", padx=2)
        self.form = Scroll(right)
        self.form.pack(fill="both", expand=True)

    def set_sashes(self):
        try:
            self.pw.sashpos(0, 175)
            self.pw.sashpos(1, 560)
        except tk.TclError:
            pass

    def tname(self, n):
        t = self.data.t[n]
        return ("● " if t.dirty else "") + CFG.get(n, {}).get("title", n)

    def fill_tables(self):
        t = self.tlist
        t.delete(*t.get_children())
        fav = t.insert("", "end", iid="__fav", text="よく使う", open=True)
        oth = t.insert("", "end", iid="__oth", text="そのほかの表", open=False)
        for n in CFG:
            if n in self.data.t:
                t.insert(fav, "end", iid=n, text=self.tname(n))
        for n in sorted(self.data.t):
            if n not in CFG:
                t.insert(oth, "end", iid=n, text=self.tname(n))
        t.bind("<<TreeviewSelect>>", self.on_table)

    def touch(self, tb):
        self.tlist.item(tb.name, text=self.tname(tb.name))
        n = sum(1 for x in self.data.t.values() if x.dirty)
        self.status.config(text=f"未保存の表: {n}" if n else "")

    def log(self, s):
        self.logw.config(state="normal")
        self.logw.insert("end", s + "\n")
        self.logw.see("end")
        self.logw.config(state="disabled")

    # ---------- 表と行 ----------
    def cols_for(self, tb):
        show = CFG.get(tb.name, {}).get("show") or tb.cols[1:5]
        return [c for c in show if c in tb.cols and c != tb.cols[0]]

    def row_values(self, tb, row, show):
        d, cfg = self.data, CFG.get(tb.name, {})
        v = [row[0], d.row_name(tb, row)]
        if cfg.get("extra"):
            v.append(d.materials(tb, row))
        for c in show:
            i = tb.cols.index(c)
            v.append(short(row[i]) if tb.kinds[i] == "float" else row[i])
        return v

    def fill_rows(self):
        tb, t = self.cur, self.rtree
        self._lock = True
        t.delete(*t.get_children())
        if tb is not None:
            show = self.cols_for(tb)
            extra = CFG.get(tb.name, {}).get("extra")
            heads = [tb.cols[0], "名前"] + ([extra[0]] if extra else []) + [label(c).split(" (")[0] for c in show]
            t.configure(columns=[f"c{i}" for i in range(len(heads))])
            for i, h in enumerate(heads):
                t.heading(f"c{i}", text=h)
                wide = 170 if (i == 2 and extra) else 140 if i == 1 else 70 if i == 0 else 90
                t.column(f"c{i}", width=wide, minwidth=50, stretch=False)
            q = self.q.get().strip().lower()
            for ri, row in enumerate(tb.rows):
                vals = self.row_values(tb, row, show)
                if q and q not in " ".join(map(str, vals)).lower() and q not in " ".join(row).lower():
                    continue
                t.insert("", "end", iid=str(ri), values=vals)
            if self.ri is not None and t.exists(str(self.ri)):
                t.selection_set(str(self.ri))
                t.see(str(self.ri))
        self._lock = False

    def refresh_names(self):
        tb = self.cur
        show = self.cols_for(tb)
        for iid in self.rtree.get_children():
            self.rtree.item(iid, values=self.row_values(tb, tb.rows[int(iid)], show))

    def on_table(self, _=None):
        if self._lock:
            return
        s = self.tlist.selection()
        if not s or s[0].startswith("__"):
            return
        if not self.commit():
            self._lock = True
            self.tlist.selection_set(self.cur.name)
            self._lock = False
            return
        self.cur, self.ri = self.data.t[s[0]], None
        self._lock = True
        self.q.set("")
        self._lock = False
        self.build_form()
        self.fill_rows()
        self.load_row()

    def on_row(self, _=None):
        if self._lock or self.cur is None:
            return
        s = self.rtree.selection()
        new = int(s[0]) if s else None
        if new is None or new == self.ri:
            return
        if not self.commit():
            self._lock = True
            if self.ri is not None and self.rtree.exists(str(self.ri)):
                self.rtree.selection_set(str(self.ri))
            self._lock = False
            return
        self.ri = new
        self.load_row()

    def select(self, ri):
        self._lock = True
        self.rtree.selection_set(str(ri))
        self.rtree.see(str(ri))
        self._lock = False

    # ---------- フォーム ----------
    def make_field(self, parent, tb, i):
        c, k = tb.cols[i], tb.kinds[i]
        vals = {r[i] for r in tb.rows}
        if k == "int" and re.match(r"(is|can|enable|use|deny|ignore)_", c) and vals <= {"0", "1"}:
            v = tk.IntVar()
            w = ttk.Checkbutton(parent, variable=v)
            return (lambda: str(v.get())), (lambda s: v.set(1 if s.strip() == "1" else 0)), w
        if k == "str" and any("\n" in r[i] or len(r[i]) > 60 for r in tb.rows[:3000]):
            w = tk.Text(parent, height=3, width=30, wrap="word")

            def st(s):
                w.delete("1.0", "end")
                w.insert("1.0", s)
            return (lambda: w.get("1.0", "end-1c")), st, w
        v = tk.StringVar()
        w = ttk.Entry(parent, textvariable=v, width=16)
        w.bind("<Return>", lambda e: self.apply())
        return v.get, v.set, w

    def mk_hint(self, get, kind, hl):
        def hint():
            hl.config(text=self.data.lookup(kind, get().strip())[:16])
        return hint

    def build_form(self):
        tb = self.cur
        f = self.form.inner
        for w in f.winfo_children():
            w.destroy()
        self.fields, self.textw = [], []
        f.columnconfigure(1, weight=1, minsize=150)
        r = 0
        texts = CFG.get(tb.name, {}).get("texts")
        if texts:
            ttk.Label(f, text="テキスト (system_texts を編集します)").grid(row=r, column=0, columnspan=4, sticky="w", padx=4, pady=(4, 2))
            r += 1
            for col, lab in texts:
                ws = []
                for lang in ("日本語", "English"):
                    ttk.Label(f, text=f"{lab} {lang}").grid(row=r, column=0, sticky="ne", padx=4, pady=2)
                    w = tk.Text(f, height=2, width=30, wrap="word")
                    w.grid(row=r, column=1, columnspan=3, sticky="we", pady=2, padx=(0, 6))
                    ws.append(w)
                    r += 1
                self.textw.append((col, ws[0], ws[1]))
            ttk.Separator(f).grid(row=r, column=0, columnspan=4, sticky="we", pady=6)
            r += 1
        for i, c in enumerate(tb.cols):
            ttk.Label(f, text=label(c), wraplength=230, justify="right").grid(row=r, column=0, sticky="e", padx=4, pady=1)
            get, st, w = self.make_field(f, tb, i)
            w.grid(row=r, column=1, sticky="we", pady=1)
            hint, rk = (lambda: None), ref_kind(c)
            if rk:
                hl = ttk.Label(f, foreground="#666666", width=16, anchor="w")
                hl.grid(row=r, column=2, sticky="w", padx=4)
                hint = self.mk_hint(get, rk, hl)
                w.bind("<KeyRelease>", lambda e, h=hint: h())
                if rk != "text":
                    ttk.Button(f, text="…", width=3,
                               command=lambda rk=rk, st=st, h=hint: self.pick(rk, st, h)).grid(row=r, column=3, padx=(0, 6))
            self.fields.append((get, st, hint))
            r += 1

    def load_row(self):
        tb, ri = self.cur, self.ri
        row = tb.rows[ri] if tb is not None and ri is not None and ri < len(tb.rows) else None
        for i, (_g, st, hint) in enumerate(self.fields):
            st((short(row[i]) if tb.kinds[i] == "float" else row[i]) if row else "")
            hint()
        for col, jw, ew in self.textw:
            r = self.data.text_row.get(row[tb.cols.index(col)]) if row else None
            for w, idx in ((jw, self.data.ja), (ew, self.data.en)):
                w.delete("1.0", "end")
                w.insert("1.0", r[idx] if r else "")

    def pick(self, kind, setter, hint):
        items = self.data.choices(kind)
        top = tk.Toplevel(self)
        top.title("選択")
        top.geometry("360x440")
        top.transient(self)
        var = tk.StringVar()
        e = ttk.Entry(top, textvariable=var)
        e.pack(fill="x", padx=6, pady=6)
        e.focus_set()
        lb = tk.Listbox(top, activestyle="dotbox")
        lb.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        shown = []

        def refresh(*_):
            q = var.get().lower()
            lb.delete(0, "end")
            shown.clear()
            for i, n in items:
                s = f"{i}  {n}"
                if q in s.lower():
                    shown.append(i)
                    lb.insert("end", s)

        def ok(_=None):
            sel = lb.curselection() or ((0,) if shown else ())
            if sel:
                setter(shown[sel[0]])
                hint()
                top.destroy()

        var.trace_add("write", refresh)
        refresh()
        lb.bind("<Double-Button-1>", ok)
        lb.bind("<Return>", ok)
        e.bind("<Return>", ok)

    # ---------- 編集 ----------
    def apply_texts(self):
        tb, ri, d = self.cur, self.ri, self.data
        st, changed = d.t["system_texts"], False
        for col, jw, ew in self.textw:
            tid = tb.rows[ri][tb.cols.index(col)]
            if tid in ("", "0"):
                continue
            ja, en = jw.get("1.0", "end-1c"), ew.get("1.0", "end-1c")
            r = d.text_row.get(tid)
            if r is None:
                if not (ja or en):
                    continue
                r = [en] * len(st.cols)
                r[0], r[d.ja], r[d.en] = tid, ja, en
                st.rows.append(r)
                d.text_row[tid] = r
                changed = True
            elif (r[d.ja], r[d.en]) != (ja, en):
                r[d.ja], r[d.en] = ja, en
                changed = True
        if changed:
            st.dirty = True
            self.touch(st)
        return changed

    def commit(self):
        """フォームの内容を行に反映する。入力に問題があればFalse。"""
        tb, ri = self.cur, self.ri
        if tb is None or ri is None or ri >= len(tb.rows):
            return True
        new = []
        for i, (get, _st, _h) in enumerate(self.fields):
            v = get()
            old = tb.rows[ri][i]
            if tb.kinds[i] == "float" and short(old) == v.strip():
                new.append(old)
                continue
            try:
                new.append(tb.check(i, v))
            except ValueError:
                kind = {"int": "整数", "float": "小数"}[tb.kinds[i]]
                messagebox.showerror("入力エラー", f"「{label(tb.cols[i])}」は{kind}で入力してください。\n入力値: {v!r}")
                return False
        changed = False
        if new != tb.rows[ri]:
            tb.rows[ri] = new
            tb.dirty = True
            changed = True
            self.touch(tb)
        if self.apply_texts():
            changed = True
        if changed:
            self.data.reindex()
            self.refresh_names()
        return True

    def apply(self):
        if self.commit():
            self.status.config(text="適用しました(TSV保存・ゲーム反映はまだ)")

    def dup(self):
        tb, d = self.cur, self.data
        if tb is None or self.ri is None or not self.commit():
            return
        row = list(tb.rows[self.ri])
        col0 = [r[0] for r in tb.rows]
        if tb.kinds[0] == "int" and len(set(col0)) == len(col0):
            row[0] = str(max(int(x) for x in col0) + 1)
        st = d.t["system_texts"]
        for col, _lab in CFG.get(tb.name, {}).get("texts", []):
            i = tb.cols.index(col)
            old = d.text_row.get(row[i])
            if old:
                nid = d.new_text_id()
                nr = list(old)
                nr[0] = nid
                st.rows.append(nr)
                d.text_row[nid] = nr
                st.dirty = True
                row[i] = nid
        tb.rows.append(row)
        tb.dirty = True
        d.reindex()
        self.touch(tb)
        self.touch(st)
        self.ri = len(tb.rows) - 1
        self.q.set("") if self.q.get() else None
        self.fill_rows()
        self.select(self.ri)
        self.load_row()
        self.log(f"{tb.name}: 行を複製しました (新しいID: {row[0]})。新規IDをゲームが認識するかは未検証です。")

    def delete(self):
        tb = self.cur
        if tb is None or self.ri is None:
            return
        if not messagebox.askyesno("削除", "この行を削除します。\nゲームが参照している行を消すと、起動しなくなることがあります。続けますか?"):
            return
        del tb.rows[self.ri]
        tb.dirty = True
        self.data.reindex()
        self.touch(tb)
        self.ri = None
        self.fill_rows()
        self.load_row()

    # ---------- 保存とゲームへの反映 ----------
    def save_all(self):
        if not self.commit():
            return False
        dirty = [t for t in self.data.t.values() if t.dirty]
        if not dirty:
            self.log("変更はありません")
            return True
        bak = os.path.join(HERE, "tables_orig")
        if not os.path.exists(bak):
            shutil.copytree(TDIR, bak)
            self.log("元のTSVを tables_orig/ に保存しました")
        for t in dirty:
            t.save()
            self.touch(t)
        self.log("保存: " + ", ".join(t.name for t in dirty))
        return True

    def build(self):
        if self.save_all():
            self.core(do_build)

    def restore(self):
        if messagebox.askyesno("ゲームを元に戻す", "res.pac のマスターデータを元の状態に戻します。\nTSVの編集内容は残ります。よろしいですか?"):
            self.core(do_restore)

    def core(self, fn):
        try:
            fn(self.log)
        except (CcxError, ValueError, OSError, struct.error) as e:
            self.log(f"エラー: {e}")
            messagebox.showerror("できませんでした", str(e))
            return False
        return True

    def reset_view(self):
        self.data = Data()
        self.cur, self.ri = None, None
        for w in self.form.inner.winfo_children():
            w.destroy()
        self.fields, self.textw = [], []
        self.fill_tables()
        self.fill_rows()
        self.status.config(text="")

    def reload(self):
        if any(t.dirty for t in self.data.t.values()) and not messagebox.askyesno("読み直し", "未保存の変更は捨てられます。続けますか?"):
            return
        self.reset_view()
        self.log("TSVを読み直しました")

    def regen(self):
        if not messagebox.askyesno("作り直し", "tables/ を res.pac の元データから作り直します。\nTSVの編集内容はすべて失われます。続けますか?"):
            return
        if self.core(do_export):
            self.reset_view()

    def on_close(self):
        if not self.commit():
            return
        if any(t.dirty for t in self.data.t.values()):
            a = messagebox.askyesnocancel("終了", "未保存の変更があります。保存して終了しますか?")
            if a is None:
                return
            if a and not self.save_all():
                return
        self.destroy()


def gui_main():
    try:
        ensure_state(print)
        if not os.path.isdir(TDIR) or not any(x.endswith(".tsv") for x in os.listdir(TDIR)):
            do_export(print)
    except (CcxError, ValueError, OSError) as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Cube Creator X Studio", str(e))
        sys.exit(1)
    App().mainloop()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "gui"
    cmds = {"export": do_export, "build": do_build, "restore": do_restore, "info": do_info}
    try:
        if cmd == "gui":
            gui_main()
        elif cmd in cmds:
            cmds[cmd](print)
        else:
            print(__doc__)
    except (CcxError, ValueError, OSError) as e:
        print("エラー:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
