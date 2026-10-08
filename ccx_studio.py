#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cube Creator X Studio(単体版)

ゲームのフォルダ(res.pac がある場所)に置いて起動するだけで使えます。
    python3 ccx_studio.py            GUIを起動(初回は res.pac を自動解析して tables/ を作ります)
    python3 ccx_studio.py info       res.pac の解析結果を表示
    python3 ccx_studio.py export     tables/ を res.pac の元データから作り直す
    python3 ccx_studio.py build      tables/ の内容を res.pac に反映
    python3 ccx_studio.py restore    res.pac のマスターデータを元に戻す
    python3 ccx_studio.py icon-list [件数] / icon-export 番号 / icon-replace 番号 画像 / icon-add 画像 [名前]
        アイテムのアイコンの一覧・書き出し・差し替え・追加(GUIの「アイコン…」と同じ。元に戻すは tex-restore all)
    python3 ccx_studio.py icon-probe  (調査用)アイテムのアイコンの位置表を探して形式を表示
    python3 ccx_studio.py refs [ブロック番号]  (調査用)ブロックの位置やサイズが他の場所に書かれていないか探す
    python3 ccx_studio.py tex-list [件数] / tex-export 番号 / tex-import 番号 画像 [grow] / tex-restore 番号|all
        テクスチャの一覧・PNG書き出し・差し替え・元に戻す(GUIの「テクスチャ…」と同じ)
    必要: pip install pillow etcpak texture2ddecoder(テクスチャ機能のみ)
Linuxでtkinterが無い場合: sudo apt install python3-tk
"""
import base64, csv, hashlib, io, json, mmap, os, re, shutil, struct, subprocess, sys, zlib
from collections import Counter
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
TDIR = os.path.join(HERE, "tables")
ENC = dict(encoding="utf-8", errors="surrogateescape", newline="")

PAC = os.path.join(HERE, "res.pac")
ORIG = PAC + ".orig"    # 旧 cctool.py が作ったバックアップ(あれば元データの取得元に使う)
BACKUP = PAC + ".tblk"  # マスターデータ部分の元データ(このツールが作る。数百KB)
STATE = os.path.join(HERE, "ccx_state.json")
BLOCKS = os.path.join(HERE, "blocks.csv")
PAGE, HDR = 0x10000, 0x30
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
def have_zopfli():
    try:
        import zopfli.zlib  # noqa: F401
        return True
    except ImportError:
        return False


def deflate_best(data, log=print, limit=None):
    """zlib圧縮。limit に収まらないときは、設定違い、zopfli(入っていれば)の順に試して小さくする"""
    best = zlib.compress(data, 9)
    if limit is not None and len(best) <= limit:
        return best
    for mem, strat in ((9, zlib.Z_DEFAULT_STRATEGY), (8, zlib.Z_FILTERED), (9, zlib.Z_FILTERED)) if len(data) < (8 << 20) else ((9, zlib.Z_DEFAULT_STRATEGY),):
        c = zlib.compressobj(9, zlib.DEFLATED, 15, mem, strat)
        z = c.compress(data) + c.flush()
        if len(z) < len(best):
            best = z
        if limit is not None and len(best) <= limit:
            return best
    if limit is not None and len(best) > limit and have_zopfli():
        import zopfli.zlib as zz
        log("上限に収まらないので、zopfli で強く圧縮しています(時間がかかります)...")
        z = zz.compress(data, numiterations=15 if len(data) < (4 << 20) else 5)
        if len(z) < len(best):
            best = z
    return best


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


def master_assemble(d, heads, new_rows):
    """new_rows: {表名: 行のリスト(型つき)}。変わった表だけ作り直して、全体のバイト列を返す"""
    out, diffs, nchg = [d[:heads[0][0]]], [], 0
    for pos, name, cols, nr, start, end, old in heads:
        new = new_rows.get(name)
        if new is None or new == old:
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
    return b"".join(out), diffs, nchg


def master_prepare(st, d, nd, diffs, log):
    """圧縮して上限に収まるか確かめ、収まれば res.pac に書き込む関数を返す"""
    log("\n".join(diffs[:60]) + (f"\n... 他 {len(diffs) - 60} 件" if len(diffs) > 60 else ""))
    limit = st["comp"]
    z = deflate_best(nd, log, limit)
    log(f"マスターデータ: {len(d)} -> {len(nd)} バイト / 圧縮後 元={st['comp']} 今回={len(z)} 上限={limit}")
    if len(z) > limit:
        hint = "" if have_zopfli() else ("\n圧縮を強くするには、次のコマンドで zopfli を入れてください(約6%小さくなります):\n"
                                         "  pip install zopfli")
        raise CcxError(f"圧縮後のサイズが上限を {len(z) - limit} バイト超えました。res.pac は変更していません。"
                       "追加した行や文字を減らしてください。" + hint)

    def commit():
        off, comp = st["off"], st["comp"]
        with open(PAC, "r+b") as f:
            f.seek(off - 8)
            f.write(struct.pack("<Q", len(nd)))
            f.write(z + b"\0" * max(comp - len(z), 0))
        st["mod_sha1"] = sha1(read_region(PAC, off, comp))
        st["grown"] = 0
        save_state(st)
        log("res.pac に反映しました。")
    return commit


def do_build(log=print):
    """tables/*.tsv の変更を res.pac に反映する(元データからの差分だけを書き込む)"""
    st = ensure_state(log)
    if not os.path.isdir(TDIR):
        raise CcxError("tables/ がありません。先に export を実行してください。")
    d = original_data(st)
    heads = find_heads(d)
    new_rows = {}
    for pos, name, cols, nr, start, end, old in heads:
        path = os.path.join(TDIR, name + ".tsv")
        if os.path.exists(path):
            try:
                new_rows[name] = read_tsv(path, cols)
            except ValueError as e:
                raise CcxError(f"{name}.tsv: {e}")
    nd, diffs, nchg = master_assemble(d, heads, new_rows)
    if nchg == 0:
        log("変更がありません。マスターデータを元の状態にします。")
        do_restore(log)
        return
    master_prepare(st, d, nd, diffs, log)()


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


def do_refs(log=print, block=None):
    """ブロックの位置やサイズが、res.pac の他の場所に書かれていないかを探す(調査用)。block を省略するとマスターデータ"""
    if block is None:
        st = ensure_state(log)
        vals = {"圧縮サイズ": st["comp"], "展開サイズ": st["decomp"], "ブロックの位置": st["off"]}
    else:
        with open(BLOCKS, newline="") as f:
            r = list(csv.DictReader(f))[int(block)]
        vals = {"圧縮サイズ": int(r["comp"]), "展開サイズ": int(r["decomp"]), "ブロックの位置": int(r["offset"])}
    size = os.path.getsize(PAC)
    with open(PAC, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        for name, v in vals.items():
            for fmt in ("<I", "<Q"):
                pat, pos, hits = struct.pack(fmt, v), 0, []
                while len(hits) < 8:
                    i = mm.find(pat, pos)
                    if i < 0:
                        break
                    hits.append(i)
                    pos = i + 1
                note = []
                for h in hits:
                    tag = "ページ見出し内" if h % PAGE < HDR else "ファイル末尾付近" if h > size - 4096 else "その他"
                    note.append(f"0x{h:x}({tag})")
                log(f"{name}={v} {'4' if fmt == '<I' else '8'}バイト: " + (", ".join(note) or "なし"))


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
    "master_item_food": dict(title="食べ物", texts=[("name_text_id", "名前"), ("description_text_id", "説明")], show=["hp_recover", "hungry_recover", "buff_seconds"]),
    "master_equip": dict(title="装備(武器・防具)", texts=[("name_text_id", "名前"), ("description_text_id", "説明")], show=["equip_category", "damage", "defense_rate", "critical_rate"]),
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


# ---------------------------------------------------------------- テクスチャ(RAWT)の書き出しと差し替え
TEXSTATE = os.path.join(HERE, "ccx_textures.json")
TEXIDX = os.path.join(HERE, "ccx_texindex.json")
TEXBAK = PAC + ".texbak"
TEXDIR = os.path.join(HERE, "textures")
# ヘッダ 'RAWT' + 幅(2) + 高さ(2) + 形式コード(4) + サイズ(4) の16バイトの後ろに画素データが続く。
# 1ピクセル4バイトのもの(形式コード 0x10)は無圧縮、1ピクセル1バイトのもの(0xba)は BC7 と見られる。
DEC_SNIPPET = (
    "import sys, texture2ddecoder as T\\n"
    "w, h = int(sys.argv[1]), int(sys.argv[2])\\n"
    "sys.stdout.buffer.write(T.decode_bc7(sys.stdin.buffer.read(), w, h))\\n"
).replace("\\n", "\n")


def need_pil():
    try:
        from PIL import Image
        import etcpak
    except ImportError:
        raise CcxError("画像の変換に pillow と etcpak と texture2ddecoder が必要です。次のコマンドで入れてください:\n"
                       "  pip install pillow etcpak texture2ddecoder")
    return Image, etcpak


def tex_index(log=print, force=False):
    """res.pac 内の RAWT テクスチャの一覧(ブロック番号、位置、大きさ、名前)"""
    size = os.path.getsize(PAC)
    if not force and os.path.exists(TEXIDX):
        try:
            with open(TEXIDX, encoding="utf-8") as f:
                j = json.load(f)
            if j.get("size") == size and j.get("version") == 1:
                return j["items"]
        except (OSError, ValueError):
            pass
    log("テクスチャの一覧を作っています(初回のみ。数秒かかります)...")
    if not os.path.exists(BLOCKS):
        src = ORIG if os.path.exists(ORIG) and os.path.getsize(ORIG) == size else PAC
        write_blocks_csv(scan(src, log))
    with open(BLOCKS, newline="") as f:
        rows = list(csv.DictReader(f))
    items, pending = [], None
    with open(PAC, "rb") as f:
        for i, r in enumerate(rows):
            off, comp, dec = int(r["offset"]), int(r["comp"]), int(r["decomp"])
            f.seek(off)
            head = zlib.decompressobj().decompress(f.read(min(comp, 512)), 16)
            if head[8:12] == b"res_" and dec < (1 << 20):
                f.seek(off)
                d = zlib.decompress(f.read(comp))
                pending = d[8:8 + struct.unpack_from("<I", d, 4)[0]].decode("latin1")
                continue
            if head[:4] == b"RAWT":
                w, h, code, sz = struct.unpack_from("<HHII", head, 4)
                items.append(dict(block=i, off=off, comp=comp, w=w, h=h, code=code, size=sz, dec=dec, name=pending))
            pending = None
    with open(TEXIDX, "w", encoding="utf-8") as f:
        json.dump(dict(version=1, size=size, items=items), f)
    log(f"テクスチャ {len(items)} 個(名前つき {sum(1 for x in items if x['name'])} 個)")
    return items


def tex_kind(it):
    if it["dec"] != it["size"] + 16 or not it["w"] * it["h"]:
        return None
    r = it["size"] / (it["w"] * it["h"])
    return "raw" if r == 4 else "bc7" if r == 1 else None


def tex_state():
    try:
        with open(TEXSTATE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st.setdefault("order", "RGBA")
    st.setdefault("blocks", {})
    return st


def tex_save(st):
    with open(TEXSTATE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


def tex_bak(block):
    return os.path.join(TEXBAK, f"{block}.bin")


def tex_rec(it, st):
    """差し替えの記録。ゲームの更新などで res.pac が変わっていたら、記録を捨てて None を返す"""
    rec = st["blocks"].get(str(it["block"]))
    if not rec:
        return None
    n = max(rec["comp"], rec.get("written", 0))
    if sha1(read_region(PAC, rec["off"], rec["comp"])) == rec["orig_sha1"] or \
            sha1(read_region(PAC, rec["off"], n)) == rec["mod_sha1"]:
        return rec
    st["blocks"].pop(str(it["block"]), None)
    if os.path.exists(tex_bak(it["block"])):
        os.remove(tex_bak(it["block"]))
    tex_save(st)
    return None


def tex_verify(it):
    """記録の無いブロックについて、res.pac 上の実際のブロックを確かめ、圧縮サイズを正しい値にする"""
    d, got, n_out, head = zlib.decompressobj(), 0, 0, b""
    try:
        with open(PAC, "rb") as f:
            f.seek(it["off"])
            while True:
                chunk = f.read(1 << 18)
                if not chunk:
                    break
                o = d.decompress(chunk)
                n_out += len(o)
                head = (head + o)[:16] if len(head) < 16 else head
                got += len(chunk)
                if d.eof:
                    got -= len(d.unused_data)
                    break
    except zlib.error:
        n_out = -1
    bad = not d.eof or n_out != it["dec"]
    if "w" in it and (head[:4] != b"RAWT" or struct.unpack_from("<HH", head, 4) != (it["w"], it["h"])):
        bad = True
    if bad:
        for fn in (TEXIDX, ICONIDX):
            if os.path.exists(fn):
                os.remove(fn)
        raise CcxError("res.pac の内容が、一覧を作ったときと変わっています(ゲームの更新など)。"
                       "一覧を作り直しますので、画面を開き直してください。")
    it["comp"] = got


def tex_data(it, st=None, orig=False):
    """現在の res.pac にあるブロック(展開後)。orig=True なら、差し替え前の元のデータ"""
    rec = (st or tex_state())["blocks"].get(str(it["block"]))
    if orig and rec and os.path.exists(tex_bak(it["block"])):
        with open(tex_bak(it["block"]), "rb") as f:
            return zlib.decompress(f.read()[8:])
    n = max(rec["comp"], rec.get("written", 0)) if rec else it["comp"]
    return zlib.decompress(read_region(PAC, it["off"], n)[8:])


def tex_image(it, data, order):
    Image, _e = need_pil()
    w, h, p = it["w"], it["h"], data[16:]
    kind = tex_kind(it)
    if kind == "raw":
        return Image.frombytes("RGBA", (w, h), p, "raw", order)
    if kind == "bc7":
        r = subprocess.run([sys.executable, "-c", DEC_SNIPPET, str(w), str(h)], input=p, capture_output=True, timeout=120)
        if r.returncode != 0 or len(r.stdout) != w * h * 4:
            raise CcxError("BC7を復号できませんでした(texture2ddecoder が入っているか確認してください)")
        return Image.frombytes("RGBA", (w, h), r.stdout, "raw", "BGRA")
    raise CcxError("この形式のテクスチャには未対応です")


def tex_png_path(it):
    nm = re.sub(r"[^A-Za-z0-9_-]+", "_", (it["name"] or "noname").replace("res_", "", 1))[:60]
    return os.path.join(TEXDIR, f"{it['block']:04d}_{nm}_{it['w']}x{it['h']}.png")


def do_tex_export(it, log=print):
    st = tex_state()
    os.makedirs(TEXDIR, exist_ok=True)
    path = tex_png_path(it)
    tex_image(it, tex_data(it, st), st["order"]).save(path)
    log(f"書き出しました: {os.path.relpath(path, HERE)}")
    return path


def tex_prepare(it, new, grow, log):
    """新しいブロック内容(展開後)を圧縮し、収まるか確かめる。収まれば、書き込みを行う関数を返す"""
    st = tex_state()
    rec = tex_rec(it, st)
    if not rec:
        tex_verify(it)
    off, comp = it["off"], (rec["comp"] if rec else it["comp"])
    room = -(-(off + comp - HDR) // PAGE) * PAGE - off
    limit = room if grow else comp
    if len(new) > (4 << 20):
        log("大きな画像なので、圧縮に時間がかかります(数十秒〜数分)...")
    z = deflate_best(new, log, limit)
    log(f"ブロック {it['block']}: 圧縮後 {len(z)} バイト(元のサイズ {comp} / 余白込みの上限 {room})")
    if len(z) > limit:
        raise CcxError(f"圧縮後のサイズが上限より {len(z) - limit} バイト大きくなり、収まりません。res.pac は変更していません。\n"
                       "細かい模様やノイズを減らす(平らな色を増やす)と収まりやすくなります。"
                       + ("" if have_zopfli() else "\npip install zopfli を入れると、約6%小さくなります。")
                       + ("" if grow else "\n(余白を使うオプションもあります。実験的です)"))
    if len(z) > comp:
        log(f"元のサイズを {len(z) - comp} バイト超えたので、ページの余白に書きます(実験的)。")

    def commit():
        nonlocal rec
        st = tex_state()
        if not rec:
            orig = read_region(PAC, off, comp)
            os.makedirs(TEXBAK, exist_ok=True)
            with open(tex_bak(it["block"]), "wb") as f:
                f.write(orig)
            rec = dict(off=off, comp=comp, orig_sha1=sha1(orig))
        before = max(comp, rec.get("written", 0))
        with open(PAC, "r+b") as f:
            f.seek(off - 8)
            f.write(struct.pack("<Q", len(new)))
            f.write(z + b"\0" * max(before - len(z), 0))
        rec["written"] = len(z)
        rec["mod_sha1"] = sha1(read_region(PAC, off, max(comp, len(z))))
        st["blocks"][str(it["block"])] = rec
        tex_save(st)
    return commit


def do_tex_import(it, png, grow=False, log=print):
    Image, etcpak = need_pil()
    st = tex_state()
    kind = tex_kind(it)
    if kind is None:
        raise CcxError("この形式のテクスチャには未対応です")
    im = Image.open(png).convert("RGBA")
    if im.size != (it["w"], it["h"]):
        log(f"画像の大きさが違うので {im.size[0]}x{im.size[1]} から {it['w']}x{it['h']} に縮尺します")
        im = im.resize((it["w"], it["h"]), Image.LANCZOS)
    cur = tex_data(it, st)
    payload = im.tobytes("raw", st["order"]) if kind == "raw" else bytes(etcpak.compress_bc7(im.tobytes(), it["w"], it["h"]))
    tex_prepare(it, cur[:16] + payload, grow, log)()
    log(f"テクスチャ {it['block']} を差し替えました。")


def do_tex_restore(items, log=print):
    """items が None のときは、記録のあるブロック(テクスチャ・アイコンの位置表)をすべて戻す"""
    st = tex_state()
    if items is None:
        items = [{"block": int(k)} for k in st["blocks"]]
    n = 0
    for it in items:
        rec = tex_rec(it, st)
        if not rec:
            continue
        with open(tex_bak(it["block"]), "rb") as f:
            orig = f.read()
        with open(PAC, "r+b") as f:
            f.seek(rec["off"] - 8)
            f.write(orig)
            if rec.get("written", 0) > rec["comp"]:
                f.write(b"\0" * (rec["written"] - rec["comp"]))
        os.remove(tex_bak(it["block"]))
        st["blocks"].pop(str(it["block"]), None)
        n += 1
    tex_save(st)
    log(f"テクスチャを {n} 個、元に戻しました。")
    return n


def do_icon_probe(log=print):
    """アイテムのアイコンの位置表(アトラス情報)を探して、中身の形式を調べる(調査用)"""
    if not os.path.exists(BLOCKS):
        raise CcxError("blocks.csv がありません。先に python3 ccx_studio.py info を実行してください。")
    with open(BLOCKS, newline="") as f:
        rows = list(csv.DictReader(f))
    found = []
    with open(PAC, "rb") as f:
        def block(i):
            f.seek(int(rows[i]["offset"]))
            return zlib.decompress(f.read(int(rows[i]["comp"])))
        for i, r in enumerate(rows):
            if int(r["decomp"]) > (8 << 20):
                continue
            f.seek(int(r["offset"]))
            head = zlib.decompressobj().decompress(f.read(min(int(r["comp"]), 512)), 24)
            if head[:4] in (b"RAWT", b"OggS") or head[8:24] == b"system_parameter":
                continue
            d = block(i)
            n = d.count(b"ItemIcon")
            if n >= 20:
                found.append((i, n, d))
        log(f"'ItemIcon' を20回以上含むブロック: {[(i, n, len(d)) for i, n, d in found]}")
        for i, n, d in found[:3]:
            log(f"\n===== ブロック {i} ({len(d)} バイト, ItemIcon x{n}) =====")
            ms = list(re.finditer(rb"res_Item_ItemIcon[A-Za-z0-9_]*", d))
            log(f"名前の数: {len(ms)}")
            if not ms:
                continue
            first = ms[0].start()
            log(f"最初の名前の手前 48 バイト: {d[max(0, first - 52):first].hex(' ')}")
            gaps = Counter()
            for k, m in enumerate(ms):
                lenfield = struct.unpack_from("<I", d, m.start() - 4)[0] if m.start() >= 4 else -1
                nxt = ms[k + 1].start() - 4 if k + 1 < len(ms) else len(d)
                gaps[nxt - m.end()] += 1
                if k < 6:
                    seg = d[m.end():nxt]
                    fl = [round(x, 4) for x in struct.unpack_from(f"<{min(len(seg) // 4, 12)}f", seg)] if len(seg) >= 4 else []
                    log(f"  [{k}] 長さ欄={lenfield} 名前の長さ={len(m.group())} ...{m.group()[-34:].decode('latin1')}\n"
                        f"      名前の後ろ {len(seg)} バイト: {seg[:64].hex(' ')}\n      float と読むと: {fl}")
            log(f"名前と次の名前の間の長さの分布: {gaps.most_common(6)}")
            for j in range(max(0, i - 2), min(len(rows), i + 4)):
                f.seek(int(rows[j]["offset"]))
                h = zlib.decompressobj().decompress(f.read(min(int(rows[j]["comp"]), 512)), 16)
                if h[:4] == b"RAWT":
                    w, hh, code, sz = struct.unpack_from("<HHII", h, 4)
                    log(f"  隣 ブロック{j}: テクスチャ {w}x{hh} 形式コード={hex(code)}")
                else:
                    log(f"  隣 ブロック{j}: データ {rows[j]['decomp']} バイト 先頭 {h.hex(' ')}")


# ---------------------------------------------------------------- アイテムのアイコン(アトラス)
ICONIDX = os.path.join(HERE, "ccx_icons.json")
ICONPATH = b"res/Item/ItemIcon.rwt"
# 位置表のブロック: u32 個数 + [名前(u32長+文字) + パス(u32長+文字) + float7個(x, y, 幅, 高さ, 中心x, 中心y, 0)] × 個数 + 末尾の別データ
# アトラスは位置表のすぐ後ろの RAWT(BC7)。BC7は4x4ピクセルを16バイトで表すので、変えたい部分のブロックだけ入れ替えられる。


def icon_locate(log=print):
    """(位置表のブロック, アトラスのブロック) を返す"""
    size = os.path.getsize(PAC)
    try:
        with open(ICONIDX, encoding="utf-8") as f:
            j = json.load(f)
        if j.get("size") == size:
            return j["info"], j["atlas"]
    except (OSError, ValueError):
        pass
    log("アイコンの位置表を探しています(初回のみ)...")
    items = tex_index(log)
    with open(BLOCKS, newline="") as f:
        rows = list(csv.DictReader(f))
    isr = {it["block"] for it in items}
    with open(PAC, "rb") as f:
        for i, r in enumerate(rows):
            if i in isr or int(r["decomp"]) > (8 << 20) or int(r["decomp"]) < 1000:
                continue
            f.seek(int(r["offset"]))
            raw_ = f.read(int(r["comp"]))
            head = zlib.decompressobj().decompress(raw_[:512], 24)
            if head[:2] == b"Og" or head[8:24] == b"system_parameter":
                continue
            d = zlib.decompress(raw_)
            if d.count(ICONPATH) >= 3 and struct.unpack_from("<I", d, 0)[0] == d.count(ICONPATH):
                nxt = next((it for it in items if it["block"] > i), None)
                if nxt is None:
                    break
                info = dict(block=i, off=int(r["offset"]), comp=int(r["comp"]), dec=int(r["decomp"]))
                with open(ICONIDX, "w", encoding="utf-8") as g:
                    json.dump(dict(size=size, info=info, atlas=nxt), g)
                return info, nxt
    raise CcxError("アイコンの位置表が見つかりませんでした。python3 ccx_studio.py icon-probe の結果を教えてください。")


def icon_parse(d):
    n = struct.unpack_from("<I", d, 0)[0]
    p, ents = 4, []
    for _ in range(n):
        s = p
        L = struct.unpack_from("<I", d, p)[0]
        name = d[p + 4:p + 4 + L].decode("latin1")
        p += 4 + L
        L2 = struct.unpack_from("<I", d, p)[0]
        path = d[p + 4:p + 4 + L2]
        p += 4 + L2
        rect = struct.unpack_from("<7f", d, p)
        p += 28
        ents.append(dict(name=name, path=path, rect=rect, raw=d[s:p]))
    return ents, d[p:]


def icon_box(rect, H, flip):
    x, y, w, h = int(round(rect[0])), int(round(rect[1])), int(round(rect[2])), int(round(rect[3]))
    return x, (H - y - h if flip else y), w, h


def bc7_decode(payload, w, h):
    need_pil()
    Image = need_pil()[0]
    r = subprocess.run([sys.executable, "-c", DEC_SNIPPET, str(w), str(h)], input=payload, capture_output=True, timeout=300)
    if r.returncode != 0 or len(r.stdout) != w * h * 4:
        raise CcxError("BC7を復号できませんでした(texture2ddecoder が入っているか確認してください)")
    return Image.frombytes("RGBA", (w, h), r.stdout, "raw", "BGRA")


def atlas_region(payload, W, x, y, w, h):
    """4x4ブロック単位で囲んだ範囲 → (復号した画像, ブロック範囲)"""
    bx0, by0, bx1, by1 = x // 4, y // 4, -(-(x + w) // 4), -(-(y + h) // 4)
    cols = W // 4
    region = b"".join(payload[(by * cols + bx0) * 16:(by * cols + bx1) * 16] for by in range(by0, by1))
    return bc7_decode(region, (bx1 - bx0) * 4, (by1 - by0) * 4), (bx0, by0, bx1, by1)


def atlas_crop(payload, W, box):
    x, y, w, h = box
    im, (bx0, by0, _a, _b) = atlas_region(payload, W, x, y, w, h)
    return im.crop((x - bx0 * 4, y - by0 * 4, x - bx0 * 4 + w, y - by0 * 4 + h))


def atlas_paste(payload, W, box, im):
    """画像 im を box の位置に入れる。関係する4x4ブロックだけを作り直し、他のバイトは変えない"""
    _I, etcpak = need_pil()
    x, y, w, h = box
    cur, (bx0, by0, bx1, by1) = atlas_region(payload, W, x, y, w, h)
    cur.paste(im, (x - bx0 * 4, y - by0 * 4))
    enc = bytes(etcpak.compress_bc7(cur.tobytes(), cur.width, cur.height))
    out, cols, n = bytearray(payload), W // 4, (bx1 - bx0) * 16
    for k, by in enumerate(range(by0, by1)):
        out[(by * cols + bx0) * 16:(by * cols + bx0) * 16 + n] = enc[k * n:(k + 1) * n]
    return bytes(out)


def icon_load(log=print, orig=False):
    info, atlas = icon_locate(log)
    st = tex_state()
    ents, tail = icon_parse(tex_data(info, st, orig))
    return info, atlas, ents, tail


def icon_image(atlas, ent, flip, st=None):
    d = tex_data(atlas, st)
    return atlas_crop(d[16:], atlas["w"], icon_box(ent["rect"], atlas["h"], flip))


def do_icon_replace(ent_name, png, log=print):
    Image, _e = need_pil()
    st = tex_state()
    info, atlas, ents, tail = icon_load(log)
    ent = next((e for e in ents if e["name"] == ent_name), None)
    if ent is None:
        raise CcxError(f"アイコン {ent_name} がありません")
    box = icon_box(ent["rect"], atlas["h"], st.get("flip_y", False))
    im = Image.open(png).convert("RGBA")
    if im.size != (box[2], box[3]):
        log(f"画像の大きさが違うので {im.size[0]}x{im.size[1]} から {box[2]}x{box[3]} に縮尺します")
        im = im.resize((box[2], box[3]), Image.LANCZOS)
    cur = tex_data(atlas, st)
    new = cur[:16] + atlas_paste(cur[16:], atlas["w"], box, im)
    tex_prepare(atlas, new, False, log)()
    log(f"アイコン {ent_name} を差し替えました。")


def icon_free_slot(boxes, W, H, w, h):
    """アトラスの空きを探す。boxes は使用中の範囲 (x, y, 幅, 高さ) のリスト。4の倍数の位置を返す"""
    cw, ch = W // 4, H // 4
    occ = bytearray(cw * ch)
    for x, y, ew, eh in boxes:
        for cy in range(max(0, (y - 1) // 4), min(ch, (y + eh) // 4 + 1)):
            row = cy * cw
            for cx in range(max(0, (x - 1) // 4), min(cw, (x + ew) // 4 + 1)):
                occ[row + cx] = 1
    pre = [[0] * (cw + 1) for _ in range(ch + 1)]
    for cy in range(ch):
        s = 0
        for cx in range(cw):
            s += occ[cy * cw + cx]
            pre[cy + 1][cx + 1] = pre[cy][cx + 1] + s
    gw, gh = -(-w // 4), -(-h // 4)
    for cy in range(0, ch - gh, 8):
        for cx in range(0, cw - gw, 8):
            if pre[cy + gh][cx + gw] - pre[cy][cx + gw] - pre[cy + gh][cx] + pre[cy][cx] == 0:
                return cx * 4, cy * 4
    raise CcxError("アトラスに空きがありません")


def icon_add_many(adds, log=print, orig=False, reserved=()):
    """新しいアイコンをまとめて追加する。adds: [(名前, PIL画像, 位置 (x,y,幅,高さ) または None)]。
    orig=True なら、差し替え前の元のデータに足す。reserved は、使わない予約済みの範囲。
    戻り値: (書き込む関数, {名前: (x, y, 幅, 高さ)})"""
    Image, _e = need_pil()
    st = tex_state()
    info, atlas, ents, tail = icon_load(log, orig)
    W, H, flip = atlas["w"], atlas["h"], st.get("flip_y", False)
    size = Counter((int(e["rect"][2]), int(e["rect"][3])) for e in ents).most_common(1)[0][0]
    boxes = [icon_box(e["rect"], H, flip) for e in ents] + list(reserved)
    names = {e["name"] for e in ents}
    cur = tex_data(atlas, st, orig)
    payload, head16 = cur[16:], cur[:16]
    body = tex_data(info, st, orig)
    body = body[4:len(body) - len(tail)]
    placed, entries = {}, b""
    for name, im, rect in adds:
        if name in names:
            raise CcxError(f"{name} は既にあります")
        names.add(name)
        im = im.convert("RGBA").resize(size, Image.LANCZOS)
        if rect:
            x, y = rect[0], rect[1]
        else:
            x, y = icon_free_slot(boxes, W, H, size[0], size[1])
        boxes.append((x, y, size[0], size[1]))
        payload = atlas_paste(payload, W, (x, y, size[0], size[1]), im)
        ry = H - y - size[1] if flip else y
        nb = name.encode()
        entries += (struct.pack("<I", len(nb)) + nb + struct.pack("<I", len(ICONPATH)) + ICONPATH
                    + struct.pack("<7f", float(x), float(ry), float(size[0]), float(size[1]), size[0] / 2, size[1] / 2, 0.0))
        placed[name] = (x, y, size[0], size[1])
        log(f"アトラスの (x={x}, y={y}) に {size[0]}x{size[1]} で {name[-40:]} を追加します")
    new_info = struct.pack("<I", len(ents) + len(adds)) + body + entries + tail
    c_atlas = tex_prepare(atlas, head16 + payload, False, log)
    c_info = tex_prepare(info, new_info, False, log)

    def commit():
        c_atlas()
        c_info()
    return commit, placed


def do_icon_add(png, name=None, log=print):
    """新しいアイコンをアトラスの空きに追加し、位置表にも1行足す。追加した名前を返す"""
    Image, _e = need_pil()
    info, atlas, ents, tail = icon_load(log)
    names = {e["name"] for e in ents}
    if not name:
        k = 1
        while f"res_Item_ItemIcon_IMAGE_IMAGE_ICON_ICON_CUSTOM_{k:03d}_TGA" in names:
            k += 1
        name = f"res_Item_ItemIcon_IMAGE_IMAGE_ICON_ICON_CUSTOM_{k:03d}_TGA"
    commit, _p = icon_add_many([(name, Image.open(png), None)], log)
    commit()
    log(f"新しいアイコン {name} を追加しました。")
    return name


def do_icon_restore(log=print):
    info, atlas = icon_locate(log)
    return do_tex_restore([info, atlas], log)


def tex_find(n):
    for it in tex_index():
        if it["block"] == int(n):
            return it
    raise CcxError(f"ブロック {n} はテクスチャではありません")



# ---------------------------------------------------------------- mod の書き出し(配布用のzip)
# ゲームのデータ(元の表、テキスト、画像)は入れず、「元にした既存の行のID」と「違う部分の値」、
# 自分の文章、自分で追加したアイコンだけを書き出す。導入する人のゲームから、元の中身が読み込まれる。
MOD_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,31}$")
MOD_HANDLED = {"master_item", "master_item_food", "master_equip", "master_craft", "system_texts"}


def mod_typed(t, s):
    if t in (1, 61):
        return int(s)
    if t == 12:
        return float(short(s))
    return s


def mod_slug(text, fallback):
    k = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:24]
    return k if len(k) >= 2 else fallback


def mod_best(orig_rows, row, skip):
    """行 row にいちばん似ている元の行(違うセルの数が最小)"""
    best, bn = None, 1 << 30
    for r in orig_rows:
        n = sum(1 for i, (a, b) in enumerate(zip(r, row)) if i not in skip and a != b)
        if n < bn:
            best, bn = r, n
    return best


def mod_export(data, meta, out_path, log=print):
    """編集中の表(Data)と、元のゲームのデータとの違いだけを、modのzipにする"""
    import zipfile
    if not MOD_ID_RE.match(meta.get("id", "")):
        raise CcxError("modのID は、英小文字・数字・_ だけで2〜32文字にしてください(例: ruby_pack)")
    for k, nm in (("name", "名前"), ("author", "作者"), ("version", "バージョン")):
        if not meta.get(k, "").strip():
            raise CcxError(f"modの{nm}を入力してください")
    st = ensure_state(log)
    heads = find_heads(original_data(st))
    ocols = {h[1]: h[2] for h in heads}
    orig = {h[1]: [[str(v) for v in r] for r in h[6]] for h in heads}
    cur = {n: t for n, t in data.t.items()}
    errors, warns, items, recipes, rows, patches, icons = [], [], [], [], [], [], {}
    orig_text = {r[0]: r for r in orig["system_texts"]}
    game_strings = {x for r in orig["system_texts"] for x in r[1:] if x}
    ix = {n: {c: i for i, (t, c) in enumerate(cols)} for n, cols in ocols.items()}
    ctext = {r[0]: r for r in cur["system_texts"].rows}
    ti = ix["system_texts"]

    def typed(table, col, s):
        return mod_typed(ocols[table][ix[table][col]][0], s)

    def own_text(tid):
        """自分で書いた文章(元のゲームと同じ文章は除く)"""
        r = ctext.get(tid)
        if r is None:
            return None
        out = {}
        for lang, col in (("ja", "text_ja"), ("en", "text_en"), ("ko", "text_ko"), ("zh_cn", "text_zh_cn"), ("zh_tw", "text_zh_tw")):
            v = r[ti[col]]
            if v and v not in game_strings:
                out[lang] = v
        return out or None

    # --- アイテム
    oitem, citem = orig["master_item"], cur["master_item"]
    ii = ix["master_item"]
    oid = {r[0] for r in oitem}
    new_items = [r for r in citem.rows if r[0] not in oid]
    keymap, used = {}, set()
    for r in new_items:
        nm = own_text(r[ii["name_text_id"]]) or {}
        k = mod_slug(nm.get("en"), f"item_{r[0]}")
        while k in used:
            k += "_"
        used.add(k)
        keymap[r[0]] = k
    skip_i = {ii[c] for c in ("item_id", "name_text_id", "description_text_id", "icon_file_path", "sort_id", "equip_id")}
    ofood, oequip = orig["master_item_food"], orig["master_equip"]
    cfood = {r[0]: r for r in cur["master_item_food"].rows}
    cequip = {r[0]: r for r in cur["master_equip"].rows}
    info_names_now, info_names_orig = set(), set()
    try:
        _i, atlas, ents, _t = icon_load(log)
        info_names_now = {e["name"] for e in ents}
        info_names_orig = {e["name"] for e in icon_parse(tex_data(_i, tex_state(), True))[0]}
    except (CcxError, OSError, zlib.error, struct.error, StopIteration):
        atlas = ents = None
    custom = info_names_now - info_names_orig

    def refmap(table, col, s):
        v = typed(table, col, s)
        return f"@{keymap[s]}" if ref_kind(col) == "item" and s in keymap else v

    for r in new_items:
        key, tmpl = keymap[r[0]], mod_best(oitem, r, skip_i)
        it = {"key": key, "copy_from": int(tmpl[0])}
        name = own_text(r[ii["name_text_id"]])
        if not name:
            errors.append(f"アイテム {r[0]}: 名前が元のゲームのままです。自分の名前に変えてください(ゲームの文章は書き出せません)")
            name = {"ja": f"item{r[0]}"}
        it["name"] = name
        desc = own_text(r[ii["description_text_id"]])
        if desc:
            it["description"] = desc
        else:
            warns.append(f"アイテム {r[0]}: 説明が元のゲームのままなので、書き出していません(元にしたアイテムの説明が表示されます)")
        icon = r[ii["icon_file_path"]]
        if icon in custom and ents is not None:
            png = io.BytesIO()
            icon_image(atlas, next(e for e in ents if e["name"] == icon), tex_state().get("flip_y", False)).save(png, "PNG")
            icons[f"icons/{key}.png"] = png.getvalue()
            it["icon"] = f"icons/{key}.png"
        elif icon != tmpl[ii["icon_file_path"]]:
            it["icon_ref"] = icon
        sets = {}
        for c, i in ii.items():
            if i not in skip_i and r[i] != tmpl[i]:
                sets[c] = refmap("master_item", c, r[i])
        eq_id = r[ii["equip_id"]]
        if eq_id != r[0] and eq_id != tmpl[ii["equip_id"]]:
            sets["equip_id"] = typed("master_item", "equip_id", eq_id)
        if sets:
            it["set"] = sets
        if r[0] in cfood:
            fi = ix["master_item_food"]
            ft = mod_best(ofood, cfood[r[0]], {0})
            fd = {"set": {c: refmap("master_item_food", c, cfood[r[0]][i]) for c, i in fi.items() if i and cfood[r[0]][i] != ft[i]}}
            if ft[0] != tmpl[0]:
                fd["copy_from"] = int(ft[0])
            it["food"] = fd
        if eq_id == r[0] and r[0] in cequip:
            ei = ix["master_equip"]
            et = mod_best(oequip, cequip[r[0]], {0})
            ed = {"set": {c: typed("master_equip", c, cequip[r[0]][i]) for c, i in ei.items() if i and cequip[r[0]][i] != et[i]}}
            if et[0] != tmpl[ii["equip_id"]]:
                ed["copy_from"] = int(et[0])
            it["equip"] = ed
        items.append(it)
    used_icons = {r[ii["icon_file_path"]] for r in new_items}
    for n in sorted(custom - used_icons):
        warns.append(f"追加したアイコン {n[-40:]} は、どの新しいアイテムにも使われていないので、書き出していません")

    # --- レシピ
    oc, cc = orig["master_craft"], cur["master_craft"]
    ci = ix["master_craft"]
    ocid = {r[0] for r in oc}
    handled = {ci[c] for c in ("craft_id", "name_text_id", "result_item_id", "result_item_num", "sort_id")} | \
              {ci[f"src_item_{k}{n}"] for k in ("id", "num") for n in range(1, 5)} | {i for c, i in ci.items() if c.startswith("enable_")}
    for r in [x for x in cc.rows if x[0] not in ocid]:
        rec = {"key": f"recipe_{r[0]}", "result": refmap("master_craft", "result_item_id", r[ci["result_item_id"]]),
               "num": int(r[ci["result_item_num"]]), "materials": [], "stations": [c[7:] for c, i in ci.items() if c.startswith("enable_") and r[i] == "1"]}
        for n in range(1, 5):
            if r[ci[f"src_item_id{n}"]] != "0":
                rec["materials"].append({"item": refmap("master_craft", "src_item_id1", r[ci[f"src_item_id{n}"]]), "num": int(r[ci[f"src_item_num{n}"]])})
        sets = {c: typed("master_craft", c, r[i]) for c, i in ci.items() if i not in handled and (r[i] not in ("0", "0.0", "") or c == "parallel_limit")}
        if sets:
            rec["set"] = sets
        recipes.append(rec)

    # --- ほかの表の新しい行・既存の行の変更
    for name, ct in cur.items():
        o = orig.get(name)
        if o is None or name in ("system_texts",):
            continue
        keys = [r[0] for r in ct.rows]
        okeys = [r[0] for r in o]
        if len(set(okeys)) != len(okeys) or len(set(keys)) != len(keys):
            if ct.rows != o:
                warns.append(f"表 {name} は、IDが重なる形式なので、変更を書き出せません")
            continue
        ox = {r[0]: r for r in o}
        cols = ocols[name]
        for r in ct.rows:
            if r[0] in ox:
                diff = {c: refmap(name, c, r[i]) for i, (t, c) in enumerate(cols) if i and r[i] != ox[r[0]][i]}
                if diff:
                    patches.append({"table": name, "id": mod_typed(cols[0][0], r[0]), "set": diff})
            elif name not in MOD_HANDLED:
                if cols[0][0] != 1:
                    warns.append(f"表 {name} の新しい行は、IDが整数ではないので、書き出せません")
                    continue
                t = mod_best(o, r, {0})
                rows.append({"table": name, "key": f"row_{r[0]}", "copy_from": int(t[0]),
                             "set": {c: refmap(name, c, r[i]) for i, (tt, c) in enumerate(cols) if i and r[i] != t[i]}})
        if any(k not in ox for k in okeys if k not in set(keys)):
            warns.append(f"表 {name} で行が削除されています(削除は書き出せません)")
    # master_item の新しい行は items で扱うので、patches から除く
    new_ids = {r[0] for r in new_items} | {r[0] for r in cc.rows if r[0] not in ocid}
    patches = [p for p in patches if not (p["table"] in ("master_item", "master_item_food", "master_equip", "master_craft") and str(p["id"]) in new_ids)]
    if any(str(k) for k in tex_state()["blocks"]):
        warns.append("既存のテクスチャ・アイコンを差し替えた分は、ゲームの画像から作った物なので、書き出していません(自分で追加したアイコンだけが入ります)")
    if errors:
        raise CcxError("書き出せません:\n" + "\n".join(errors))
    mod = {"format": 1, "id": meta["id"], "name": meta["name"], "version": meta["version"], "author": meta["author"],
           "description": meta.get("description", ""), "license": meta.get("license", ""), "requires": [],
           "items": items, "recipes": recipes, "rows": rows, "patches": patches}
    readme = (f"{meta['name']} v{meta['version']}  by {meta['author']}\n\n{meta.get('description', '')}\n\n"
              f"License: {meta.get('license') or '(未指定)'}\n\n"
              "このmodは、Cube Creator X Forge で導入します。ゲームのデータ(元の表・テキスト・画像・音声)は含まれていません。\n"
              "mod.json は、元にする既存アイテムのIDと、違う部分の値だけを持ちます。icons/ の画像は、作者が作ったものです。\n")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mod.json", json.dumps(mod, indent=1, ensure_ascii=False))
        for n, b in sorted(icons.items()):
            z.writestr(n, b)
        z.writestr("README.txt", readme)
    log(f"mod を書き出しました: {out_path}\n  アイテム {len(items)}、レシピ {len(recipes)}、行追加 {len(rows)}、既存の変更 {len(patches)}、アイコン {len(icons)}")
    return warns


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

    def free_item_id(self, near):
        """near と同じ百番台の末尾の次(満杯なら次の百番台)。アイテム・食べ物・装備のIDと重ならない値"""
        used = {int(x) for x in self.item_row}
        for n in ("master_item_food", "master_equip"):
            if n in self.t:
                used |= {int(r[0]) for r in self.t[n].rows}
        blk = near // 100
        top = max((x for x in used if x // 100 == blk), default=near)
        return top + 1 if top + 1 <= blk * 100 + 99 else (max(used) // 100 + 1) * 100

    def next_sort_id(self, sitem):
        c = self.t["master_item"].cols
        si, ci = c.index("sort_id"), c.index("item_category")
        rows = self.t["master_item"].rows
        n = max(int(r[si]) for r in rows if r[ci] == sitem[ci]) + 1
        return n if n not in {int(r[si]) for r in rows} else int(sitem[si])

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


class TexWindow(tk.Toplevel):
    """テクスチャの一覧・プレビュー・PNGの書き出しと差し替え"""

    def __init__(self, app, items):
        super().__init__(app)
        self.app, self.items, self.cur, self.photo = app, items, None, None
        self.by = {str(it["block"]): it for it in items}
        self.title("テクスチャ")
        self.geometry("1040x700")
        self.minsize(820, 480)
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *a: self.fill())
        ttk.Label(top, text="検索:").pack(side="left")
        ttk.Entry(top, textvariable=self.q, width=24).pack(side="left", padx=4)
        self.named = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="名前つきだけ", variable=self.named, command=self.fill).pack(side="left", padx=8)
        ttk.Label(top, text="4バイト形式の色の並び:").pack(side="left", padx=(16, 2))
        self.order = tk.StringVar(value=tex_state()["order"])
        cb = ttk.Combobox(top, textvariable=self.order, values=("RGBA", "BGRA"), width=6, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", self.on_order)
        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        left = ttk.Frame(pw)
        pw.add(left, weight=3)
        self.tree = ttk.Treeview(left, columns=("block", "name", "size", "kind", "state"), show="headings", selectmode="browse")
        for c, t, w in (("block", "ブロック", 70), ("name", "名前", 250), ("size", "大きさ", 80), ("kind", "形式", 60), ("state", "状態", 90)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=(c == "name"))
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_sel)
        right = ttk.Frame(pw)
        pw.add(right, weight=2)
        self.info = ttk.Label(right, text="テクスチャを選んでください", wraplength=380, justify="left")
        self.info.pack(anchor="w", pady=4)
        self.prev = ttk.Label(right)
        self.prev.pack(pady=4)
        bt = ttk.Frame(right)
        bt.pack(fill="x", pady=4)
        for txt, cmd in (("PNGに書き出し", self.export), ("PNGで差し替え…", self.replace), ("この画像を元に戻す", self.restore1)):
            ttk.Button(bt, text=txt, command=cmd).pack(side="left", padx=2)
        ttk.Button(right, text="差し替えたものをすべて元に戻す", command=self.restore_all).pack(anchor="w", pady=2)
        self.grow = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, variable=self.grow, text="元の圧縮サイズを超えるとき、ページの余白も使う(実験的)").pack(anchor="w", pady=(8, 0))
        ttk.Label(right, foreground="#a03030", wraplength=380, justify="left",
                  text="余白に書く方式は、実機で起動しなくなったことがあります。起動しなくなったら、このツールの"
                       "「すべて元に戻す」で戻せます。").pack(anchor="w")
        ttk.Label(right, foreground="#666666", wraplength=380, justify="left",
                  text="差し替えはすぐ res.pac に書き込みます(ゲームを終了してから)。画像は元と同じ大きさにしてください"
                       "(違うと縮尺します)。色の並びが合わないときは、上の並びを切り替えて、もう一度差し替えます。").pack(anchor="w", pady=6)
        self.fill()

    def kind_label(self, it):
        return {"raw": "32bit", "bc7": "BC7"}.get(tex_kind(it), "未対応")

    def fill(self):
        st, q = tex_state(), self.q.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        for it in self.items:
            if self.named.get() and not it["name"]:
                continue
            nm = (it["name"] or "(名前なし)").replace("res_", "", 1)
            size = f"{it['w']}x{it['h']}"
            if q and q not in f"{it['block']} {nm} {size}".lower():
                continue
            state = "差し替え済み" if str(it["block"]) in st["blocks"] else ""
            self.tree.insert("", "end", iid=str(it["block"]), values=(it["block"], nm, size, self.kind_label(it), state))
        if self.cur and self.tree.exists(str(self.cur["block"])):
            self.tree.selection_set(str(self.cur["block"]))

    def run(self, fn, *a):
        try:
            return fn(*a, self.app.log)
        except (CcxError, OSError, ValueError, zlib.error, struct.error) as e:
            self.app.log(f"エラー: {e}")
            messagebox.showerror("テクスチャ", str(e), parent=self)
            return None

    def on_sel(self, _=None):
        s = self.tree.selection()
        self.cur = self.by[s[0]] if s else None
        self.show()

    def on_order(self, _=None):
        st = tex_state()
        st["order"] = self.order.get()
        tex_save(st)
        self.show()

    def show(self):
        it = self.cur
        if not it:
            return
        st = tex_state()
        state = "差し替え済み" if str(it["block"]) in st["blocks"] else "元のまま"
        head = (f"ブロック {it['block']}\n{it['name'] or '(名前なし)'}\n{it['w']}x{it['h']} / {self.kind_label(it)} / "
                f"圧縮後の上限 {it['comp']} バイト / {state}")
        try:
            im = tex_image(it, tex_data(it, st), st["order"])
            Image = need_pil()[0]
            from PIL import ImageDraw
        except (CcxError, OSError, ValueError, zlib.error) as e:
            self.info.config(text=head + f"\n表示できません: {e}")
            self.prev.config(image="")
            return
        m = max(it["w"], it["h"])
        if m > 352:
            im = im.copy()
            im.thumbnail((352, 352), Image.LANCZOS)
        else:
            k = max(1, 352 // m)
            im = im.resize((im.width * k, im.height * k), Image.NEAREST)
        bg = Image.new("RGBA", im.size, (100, 100, 100, 255))
        d = ImageDraw.Draw(bg)
        for y in range(0, im.height, 16):
            for x in range(0, im.width, 16):
                if (x // 16 + y // 16) % 2:
                    d.rectangle((x, y, x + 15, y + 15), fill=(130, 130, 130, 255))
        bg.alpha_composite(im)
        buf = io.BytesIO()
        bg.save(buf, "PNG")
        self.photo = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
        self.prev.config(image=self.photo)
        self.info.config(text=head)

    def export(self):
        if self.cur:
            path = self.run(do_tex_export, self.cur)
            if path:
                messagebox.showinfo("書き出しました", path, parent=self)

    def replace(self):
        if not self.cur:
            return
        png = filedialog.askopenfilename(parent=self, title="差し替える画像", initialdir=TEXDIR if os.path.isdir(TEXDIR) else HERE,
                                         filetypes=[("画像", "*.png *.jpg *.jpeg *.bmp *.tga *.webp"), ("すべて", "*.*")])
        if png:
            self.run(do_tex_import, self.cur, png, self.grow.get())
        self.fill()
        self.show()

    def restore1(self):
        if self.cur:
            self.run(do_tex_restore, [self.cur])
            self.fill()
            self.show()

    def restore_all(self):
        if messagebox.askyesno("元に戻す", "差し替えたテクスチャ(アイコンの変更も含む)をすべて元に戻します。続けますか?", parent=self):
            self.run(do_tex_restore, None)
            self.fill()
            self.show()


class IconWindow(tk.Toplevel):
    """アイテムのアイコン(アトラスの中の1つ1つ)の一覧・書き出し・差し替え・追加"""

    def __init__(self, app, data, on_pick=None):
        super().__init__(app)
        self.app, self.on_pick, self.photo, self.cur = app, on_pick, None, None
        self.title("アイテムのアイコン")
        self.geometry("1020x700")
        self.minsize(820, 480)
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *a: self.fill())
        ttk.Label(top, text="検索:").pack(side="left")
        ttk.Entry(top, textvariable=self.q, width=28).pack(side="left", padx=4)
        self.flip = tk.BooleanVar(value=tex_state().get("flip_y", False))
        ttk.Checkbutton(top, text="縦を反転して切り出す(絵がずれているとき)", variable=self.flip,
                        command=self.on_flip).pack(side="left", padx=16)
        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        left = ttk.Frame(pw)
        pw.add(left, weight=3)
        self.tree = ttk.Treeview(left, columns=("no", "name", "size", "pos"), show="headings", selectmode="browse")
        for c, t, w in (("no", "番号", 50), ("name", "名前", 330), ("size", "大きさ", 80), ("pos", "位置", 90)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=(c == "name"))
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_sel)
        right = ttk.Frame(pw)
        pw.add(right, weight=2)
        self.info = ttk.Label(right, text="アイコンを選んでください", wraplength=360, justify="left")
        self.info.pack(anchor="w", pady=4)
        self.prev = ttk.Label(right)
        self.prev.pack(pady=4)
        bt = ttk.Frame(right)
        bt.pack(fill="x", pady=4)
        for txt, cmd in (("PNGに書き出し", self.export), ("PNGで差し替え…", self.replace), ("新しいアイコンを追加…", self.add)):
            ttk.Button(bt, text=txt, command=cmd).pack(side="left", padx=2)
        if on_pick:
            ttk.Button(right, text="このアイコンを使う", command=self.use).pack(anchor="w", pady=4)
        ttk.Button(right, text="差し替え・追加をすべて元に戻す", command=self.restore).pack(anchor="w", pady=2)
        ttk.Label(right, foreground="#666666", wraplength=360, justify="left",
                  text="新しいアイコンは、アトラス(大きな画像)の空きに入れて、位置表に1行足します。"
                       "アイテムに使うには、アイテムの「icon_file_path」にその名前を入れて、「ゲームに反映」します。"
                       "差し替え・追加はすぐ res.pac に書き込みます(ゲームを終了してから)。").pack(anchor="w", pady=8)
        self.set_data(data)

    def set_data(self, data):
        self.info_b, self.atlas, self.ents, self.tail = data
        self.fill()

    def fill(self):
        q = self.q.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        for k, e in enumerate(self.ents):
            nm = e["name"].replace("res_Item_ItemIcon_IMAGE_IMAGE_ICON_", "", 1)
            if q and q not in f"{k} {nm}".lower():
                continue
            r = e["rect"]
            self.tree.insert("", "end", iid=str(k), values=(k, nm, f"{int(r[2])}x{int(r[3])}", f"{int(r[0])},{int(r[1])}"))
        if self.cur is not None and self.tree.exists(str(self.cur)):
            self.tree.selection_set(str(self.cur))

    def run(self, fn, *a):
        self.update_idletasks()
        try:
            return fn(*a, self.app.log)
        except (CcxError, OSError, ValueError, zlib.error, struct.error) as e:
            self.app.log(f"エラー: {e}")
            messagebox.showerror("アイコン", str(e), parent=self)
            return None

    def on_flip(self):
        st = tex_state()
        st["flip_y"] = self.flip.get()
        tex_save(st)
        self.show()

    def on_sel(self, _=None):
        s = self.tree.selection()
        self.cur = int(s[0]) if s else None
        self.show()

    def show(self):
        if self.cur is None:
            return
        e = self.ents[self.cur]
        head = f"{self.cur}: {e['name']}\nアトラス {self.atlas['w']}x{self.atlas['h']} の中の " \
               f"x={e['rect'][0]:.0f} y={e['rect'][1]:.0f} {e['rect'][2]:.0f}x{e['rect'][3]:.0f}"
        try:
            im = icon_image(self.atlas, e, self.flip.get())
            Image = need_pil()[0]
            from PIL import ImageDraw
        except (CcxError, OSError, ValueError, zlib.error) as ex:
            self.info.config(text=head + f"\n表示できません: {ex}")
            self.prev.config(image="")
            return
        k = max(1, 256 // max(im.width, im.height))
        im = im.resize((im.width * k, im.height * k), Image.NEAREST)
        bg = Image.new("RGBA", im.size, (100, 100, 100, 255))
        d = ImageDraw.Draw(bg)
        for y in range(0, im.height, 16):
            for x in range(0, im.width, 16):
                if (x // 16 + y // 16) % 2:
                    d.rectangle((x, y, x + 15, y + 15), fill=(130, 130, 130, 255))
        bg.alpha_composite(im)
        buf = io.BytesIO()
        bg.save(buf, "PNG")
        self.photo = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
        self.prev.config(image=self.photo)
        self.info.config(text=head)

    def export(self):
        if self.cur is None:
            return
        try:
            im = icon_image(self.atlas, self.ents[self.cur], self.flip.get())
            os.makedirs(TEXDIR, exist_ok=True)
            path = os.path.join(TEXDIR, f"icon_{self.cur:04d}.png")
            im.save(path)
        except (CcxError, OSError, ValueError) as e:
            messagebox.showerror("アイコン", str(e), parent=self)
            return
        self.app.log(f"書き出しました: {os.path.relpath(path, HERE)}")
        messagebox.showinfo("書き出しました", path, parent=self)

    def pick_png(self, title):
        return filedialog.askopenfilename(parent=self, title=title, initialdir=TEXDIR if os.path.isdir(TEXDIR) else HERE,
                                          filetypes=[("画像", "*.png *.jpg *.jpeg *.bmp *.tga *.webp"), ("すべて", "*.*")])

    def reload(self):
        try:
            self.set_data(icon_load(self.app.log))
        except (CcxError, OSError, ValueError) as e:
            messagebox.showerror("アイコン", str(e), parent=self)

    def replace(self):
        if self.cur is None:
            return
        png = self.pick_png("差し替える画像")
        if png:
            self.run(do_icon_replace, self.ents[self.cur]["name"], png)
            self.show()

    def add(self):
        png = self.pick_png("追加する画像")
        if not png:
            return
        name = self.run(do_icon_add, png, None)
        if name:
            self.reload()
            k = next((i for i, e in enumerate(self.ents) if e["name"] == name), None)
            if k is not None:
                self.cur = k
                self.tree.selection_set(str(k))
                self.tree.see(str(k))
            messagebox.showinfo("追加しました", f"{name}\n\nアイテムの icon_file_path にこの名前を入れて使います。", parent=self)

    def use(self):
        if self.cur is not None and self.on_pick:
            self.on_pick(self.ents[self.cur]["name"])
            self.destroy()

    def restore(self):
        if messagebox.askyesno("元に戻す", "アイコンの差し替え・追加をすべて元に戻します。続けますか?", parent=self):
            self.run(do_icon_restore)
            self.reload()
            self.show()


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

        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", padx=6)
        ttk.Button(bar2, text="全アイテムを無料クラフトに", command=self.free_craft).pack(side="left", padx=2)
        ttk.Button(bar2, text="無料クラフトを取り消す", command=self.free_craft_undo).pack(side="left", padx=2)
        ttk.Button(bar2, text="テクスチャ…", command=self.open_tex).pack(side="left", padx=(24, 2))
        ttk.Button(bar2, text="アイコン…", command=self.open_icons).pack(side="left", padx=2)
        ttk.Button(bar2, text="modとして書き出す(zip)…", command=self.export_mod).pack(side="left", padx=(24, 2))
        self.free_creative = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar2, text="クリエイティブ分類があるアイテムだけ(追加する数を減らす)",
                        variable=self.free_creative).pack(side="left", padx=14)

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
            via = texts[0][0] not in tb.cols
            ttk.Label(f, text=("リンク先アイテムの名前・説明" if via else "テキスト") + " (system_texts を編集します)").grid(row=r, column=0, columnspan=4, sticky="w", padx=4, pady=(4, 2))
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
            if c == "icon_file_path":
                ttk.Button(f, text="アイコン…", width=8,
                           command=lambda st=st: self.open_icons(st)).grid(row=r, column=3, padx=(0, 6))
            self.fields.append((get, st, hint))
            r += 1

    def load_row(self):
        tb, ri = self.cur, self.ri
        row = tb.rows[ri] if tb is not None and ri is not None and ri < len(tb.rows) else None
        for i, (_g, st, hint) in enumerate(self.fields):
            st((short(row[i]) if tb.kinds[i] == "float" else row[i]) if row else "")
            hint()
        for col, jw, ew in self.textw:
            r = self.data.text_row.get(self.tid_for(tb, row, col)) if row else None
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
    def item_of(self, tb, row):
        """食べ物・装備の行に対応する master_item の行"""
        d = self.data
        if tb.name == "master_item_food":
            return d.item_row.get(row[0])
        if tb.name == "master_equip":
            return d.item_row.get(d.equip_item.get(row[0], ""))
        return None

    def tid_for(self, tb, row, col):
        if col in tb.cols:
            return row[tb.cols.index(col)]
        it = self.item_of(tb, row)
        return it[self.data.t["master_item"].cols.index(col)] if it else ""

    def apply_texts(self):
        tb, ri, d = self.cur, self.ri, self.data
        st, changed = d.t["system_texts"], False
        for col, jw, ew in self.textw:
            tid = self.tid_for(tb, tb.rows[ri], col)
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

    def dup_linked(self, tb):
        """食べ物・装備を複製したとき、master_item にも新しいアイテムを作って結びつける"""
        d, src = self.data, tb.rows[self.ri]
        sitem = self.item_of(tb, src)
        nid = str(d.free_item_id(int(sitem[0]) if sitem else int(src[0])))
        row = list(src)
        row[0] = nid
        tb.rows.append(row)
        tb.dirty = True
        st, it = d.t["system_texts"], d.t["master_item"]
        if sitem:
            c = {n: i for i, n in enumerate(it.cols)}
            ni = list(sitem)
            ni[0] = nid
            if tb.name == "master_equip":
                ni[c["equip_id"]] = nid
            for col in ("name_text_id", "description_text_id"):
                old = d.text_row.get(ni[c[col]])
                if old:
                    tid = d.new_text_id()
                    nr = list(old)
                    nr[0] = tid
                    st.rows.append(nr)
                    d.text_row[tid] = nr
                    ni[c[col]] = tid
            ni[c["sort_id"]] = str(d.next_sort_id(sitem))
            it.rows.append(ni)
            it.dirty = st.dirty = True
            self.touch(it)
            self.touch(st)
        d.reindex()
        self.touch(tb)
        self.ri = len(tb.rows) - 1
        if self.q.get():
            self._lock = True
            self.q.set("")
            self._lock = False
        self.fill_rows()
        self.select(self.ri)
        self.load_row()
        if sitem:
            self.log(f"{tb.name}: ID {nid} を複製しました。アイテム表(master_item)にも ID {nid} を作りました。"
                     "名前などはフォーム上部で変えられます。")
        else:
            self.log(f"{tb.name}: ID {nid} を複製しました(対応するアイテムが見つからないので、アイテム表には作っていません)。")

    def dup(self):
        tb, d = self.cur, self.data
        if tb is None or self.ri is None or not self.commit():
            return
        if tb.name in ("master_item_food", "master_equip"):
            return self.dup_linked(tb)
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

    def open_tex(self):
        try:
            need_pil()
            items = tex_index(self.log)
        except (CcxError, OSError, ValueError) as e:
            messagebox.showerror("テクスチャ", str(e))
            return
        TexWindow(self, items)

    def open_icons(self, on_pick=None):
        try:
            need_pil()
            data = icon_load(self.log)
        except (CcxError, OSError, ValueError, zlib.error) as e:
            messagebox.showerror("アイコン", str(e))
            return
        IconWindow(self, data, on_pick)

    # ---------- 全アイテムを無料クラフトに ----------
    def craft_ctx(self):
        d = self.data
        cr, it = d.t.get("master_craft"), d.t["master_item"]
        if cr is None:
            raise CcxError("master_craft がありません")
        c = {n: i for i, n in enumerate(cr.cols)}
        ii = {n: i for i, n in enumerate(it.cols)}
        return d, cr, it, c, ii

    @staticmethod
    def no_material(r, c):
        return all(r[c[f"src_item_id{i}"]] in ("0", "") for i in range(1, 5))

    def free_craft(self):
        """素手で・材料なしで作れるレシピを、まだ無い全アイテムに追加する"""
        if not self.commit():
            return
        d, cr, it, c, ii = self.craft_ctx()
        have = {r[c["result_item_id"]] for r in cr.rows
                if self.no_material(r, c) and r[c["enable_empty_handed"]] == "1"}
        only = self.free_creative.get()
        targets = sorted((r for r in it.rows if r[0] != "0" and r[0] not in have and d.item_name(r[0])
                          and (not only or r[ii["creative_category"]] != "0")),
                         key=lambda r: int(r[0]))
        if not targets:
            messagebox.showinfo("無料クラフト", "追加するアイテムはありません(すべて素手で作れます)。")
            return
        if not messagebox.askyesno("全アイテムを無料クラフトに",
                                   f"材料なし・素手で作れるレシピを {len(targets)} 個、master_craft に追加します。\n"
                                   "既に素手で作れるアイテムは対象外です。\n"
                                   "(「無料クラフトを取り消す」で元に戻せます)\n続けますか?"):
            return
        votes = {}
        for r in cr.rows:
            res = d.item_row.get(r[c["result_item_id"]])
            if res:
                votes.setdefault(res[ii["item_category"]], Counter())[r[c["category"]]] += 1
        cat_of = {k: v.most_common(1)[0][0] for k, v in votes.items()}
        fallback = str(max(int(r[c["category"]]) for r in cr.rows))
        nid = max(int(r[0]) for r in cr.rows) + 1
        sort = max(int(r[c["sort_id"]]) for r in cr.rows) + 1
        for k, r in enumerate(targets):
            row = ["0.0" if kd == "float" else "" if kd == "str" else "0" for kd in cr.kinds]
            mp = int(r[ii["max_possession"]])
            row[c["craft_id"]] = str(nid + k)
            row[c["category"]] = cat_of.get(r[ii["item_category"]], fallback)
            row[c["name_text_id"]] = r[ii["name_text_id"]]
            row[c["result_item_id"]] = r[0]
            row[c["result_item_num"]] = "1"
            row[c["usable_in_stage"]] = "1"
            row[c["parallel_limit"]] = str(max(1, min(99, mp)))
            row[c["enable_empty_handed"]] = "1"
            row[c["sort_id"]] = str(sort + k)
            cr.rows.append(row)
        cr.dirty = True
        self.touch(cr)
        if self.cur is cr:
            self.fill_rows()
        self.log(f"master_craft に無料レシピを {len(targets)} 個追加しました(ID {nid} 〜 {nid + len(targets) - 1})。"
                 "「ゲームに反映」で反映されます。")

    def free_craft_undo(self):
        """無料クラフトで追加したレシピだけを取り除く"""
        if not self.commit():
            return
        d, cr, it, c, ii = self.craft_ctx()

        def mine(r):
            res = d.item_row.get(r[c["result_item_id"]])
            return (bool(res) and self.no_material(r, c) and r[c["enable_empty_handed"]] == "1"
                    and r[c["name_text_id"]] == res[ii["name_text_id"]])
        n = sum(1 for r in cr.rows if mine(r))
        if not n:
            messagebox.showinfo("無料クラフト", "取り消すレシピはありません。")
            return
        if not messagebox.askyesno("無料クラフトを取り消す", f"無料クラフトで追加したレシピ {n} 個を取り除きます。続けますか?"):
            return
        cr.rows = [r for r in cr.rows if not mine(r)]
        cr.dirty = True
        self.touch(cr)
        if self.cur is cr:
            self.ri = None
            self.fill_rows()
            self.load_row()
        self.log(f"無料クラフトのレシピを {n} 個取り除きました。")

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

    def forge_mods(self):
        """Forge で反映中のmodの名前(あれば)"""
        try:
            with open(os.path.join(HERE, "ccx_forge.json"), encoding="utf-8") as f:
                return json.load(f).get("applied", [])
        except (OSError, ValueError):
            return []

    def build(self):
        if self.forge_mods() and not messagebox.askyesno(
                "Forge のmodが入っています",
                "Forge で入れたmod(" + ", ".join(self.forge_mods()) + ")が、ゲームに反映されています。\n"
                "ここで「ゲームに反映」すると、それらのmodは外れます(Forge で、もう一度反映すると戻ります)。\n続けますか?"):
            return
        if self.save_all():
            self.core(do_build)

    def export_mod(self):
        """編集した内容を、配布用のmod(zip)として書き出す"""
        if not self.commit():
            return
        try:
            with open(os.path.join(HERE, "ccx_modmeta.json"), encoding="utf-8") as f:
                last = json.load(f)
        except (OSError, ValueError):
            last = {}
        dlg = tk.Toplevel(self)
        dlg.title("modとして書き出す")
        dlg.transient(self)
        dlg.grab_set()
        v = {k: tk.StringVar(value=last.get(k, d)) for k, d in (("id", ""), ("name", ""), ("version", "1.0.0"), ("author", ""), ("license", "CC0-1.0"))}
        f = ttk.Frame(dlg, padding=10)
        f.pack(fill="both", expand=True)
        for r, (k, lab) in enumerate((("id", "modのID(英小文字・数字・_ 、例: ruby_pack)"), ("name", "mod の名前"), ("version", "バージョン"),
                                      ("author", "作者"), ("license", "ライセンス(例: CC0-1.0, CC-BY-4.0)"))):
            ttk.Label(f, text=lab).grid(row=r, column=0, sticky="e", padx=4, pady=3)
            ttk.Entry(f, textvariable=v[k], width=36).grid(row=r, column=1, pady=3)
        ttk.Label(f, text="説明").grid(row=5, column=0, sticky="ne", padx=4, pady=3)
        desc = tk.Text(f, width=36, height=4, wrap="word")
        desc.grid(row=5, column=1, pady=3)
        desc.insert("1.0", last.get("description", ""))
        ok = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, variable=ok, text="名前・説明・アイコンは、自分で作ったものです。\nゲームの文章・画像・データは入れていません。").grid(
            row=6, column=0, columnspan=2, pady=8)
        ttk.Label(f, foreground="#666666", wraplength=420, justify="left",
                  text="書き出されるのは、新しく作ったアイテム・食べ物・武器・レシピ・行と、既存の値の変更だけです。"
                       "ゲームの元の文章や画像は入りません(元の文章のままの名前があるときは、書き出しを止めます)。"
                       "導入には Forge(ccx_forge.py)を使います。").grid(row=7, column=0, columnspan=2)

        def go():
            if not ok.get():
                messagebox.showwarning("確認", "チェックを入れてください(配布物に、ゲームの著作物を入れないための確認です)。", parent=dlg)
                return
            meta = {k: x.get().strip() for k, x in v.items()}
            meta["description"] = desc.get("1.0", "end-1c").strip()
            path = filedialog.asksaveasfilename(parent=dlg, defaultextension=".zip", initialfile=(meta["id"] or "mod") + ".zip",
                                                filetypes=[("mod (zip)", "*.zip")])
            if not path:
                return
            try:
                warns = mod_export(self.data, meta, path, self.log)
            except (CcxError, OSError, ValueError, zlib.error, struct.error) as e:
                self.log(f"エラー: {e}")
                messagebox.showerror("書き出せません", str(e), parent=dlg)
                return
            with open(os.path.join(HERE, "ccx_modmeta.json"), "w", encoding="utf-8") as g:
                json.dump({k: meta[k] for k in ("author", "license", "version")}, g, ensure_ascii=False)
            dlg.destroy()
            messagebox.showinfo("書き出しました", path + ("\n\n注意:\n- " + "\n- ".join(warns) if warns else ""))
        bt = ttk.Frame(f)
        bt.grid(row=8, column=0, columnspan=2, pady=8)
        ttk.Button(bt, text="書き出す…", command=go).pack(side="left", padx=4)
        ttk.Button(bt, text="キャンセル", command=dlg.destroy).pack(side="left", padx=4)

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
    cmds = {"export": do_export, "build": do_build, "restore": do_restore, "info": do_info, "refs": do_refs}
    arg = sys.argv[2:]
    try:
        if cmd == "gui":
            gui_main()
        elif cmd == "icon-list":
            info, atlas, ents, tail = icon_load(print)
            print(f"{len(ents)} 個 / アトラス {atlas['w']}x{atlas['h']} (ブロック {atlas['block']}) / 位置表 ブロック {info['block']}")
            for k, e in enumerate(ents[:int(arg[0]) if arg else 20]):
                print(k, e["name"], [round(x) for x in e["rect"][:4]])
        elif cmd in ("icon-export", "icon-replace") and arg:
            info, atlas, ents, tail = icon_load(print)
            e = ents[int(arg[0])] if arg[0].isdigit() else next(x for x in ents if x["name"] == arg[0])
            if cmd == "icon-export":
                os.makedirs(TEXDIR, exist_ok=True)
                path = os.path.join(TEXDIR, f"icon_{ents.index(e):04d}.png")
                icon_image(atlas, e, tex_state().get("flip_y", False)).save(path)
                print("書き出しました:", path)
            else:
                do_icon_replace(e["name"], arg[1], print)
        elif cmd == "icon-add" and arg:
            do_icon_add(arg[0], arg[1] if len(arg) > 1 else None, print)
        elif cmd == "icon-probe":
            do_icon_probe(print)
        elif cmd == "refs" and arg:
            do_refs(print, arg[0])
        elif cmd in cmds:
            cmds[cmd](print)
        elif cmd == "tex-list":
            for it in tex_index(print)[:int(arg[0]) if arg else 30]:
                print(it["block"], f"{it['w']}x{it['h']}", hex(it["code"]), it["name"] or "")
        elif cmd == "tex-export" and arg:
            do_tex_export(tex_find(arg[0]), print)
        elif cmd == "tex-import" and len(arg) >= 2:
            do_tex_import(tex_find(arg[0]), arg[1], arg[2:3] == ["grow"], print)
        elif cmd == "tex-restore" and arg:
            do_tex_restore(None if arg[0] == "all" else [tex_find(arg[0])], print)
        else:
            print(__doc__)
    except (CcxError, ValueError, OSError) as e:
        print("エラー:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
