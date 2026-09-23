"""機体詳細ページの HTML 解析。

`parse_details()` が入口で、ステータステーブルから LV ごとのレコードを組み立て、
パーツスロット・属性・出撃可否・環境適正・旋回値の正規化・強化リスト（fullst）を
順に適用する。適用順には依存関係がある:

1. build_base_records      — ステータステーブル → LV ごとの基本値
2. apply_parts_slots       — パーツスロット表の値を併合
3. apply_attr              — テーブル div の id から属性（汎用/強襲/支援）を推定
4. apply_deployment_and_env — 出撃可否・環境適正をページ全体から推定
5. apply_deployment_fallbacks — 出撃可否が取れない場合に旋回値の有無から推定
   （旋回値を見るため 1 の後、6 の前である必要がある）
6. normalize_turn_values   — 片側出撃機体の旋回キーを正しい側へ入れ替え
   （出撃可否確定後でないと判定できない）
7. apply_required_value_fallbacks — 欠損しがちな必須値（スラスター）を前 LV から補完
8. apply_fullst_fallback   — 強化リストの併合（ms_data.scraping.fullst）
9. filter_complete_records — 必須項目が揃った LV のみ残す
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from ms_data.core.labels import FIELD_MAP, clean_text, normalize_row_label
from ms_data.scraping.fullst import apply_fullst_fallback, parse_fullst_by_ms_level
from ms_data.scraping.text_values import (
    is_counter_placeholder,
    looks_like_ticket_count,
    symbol_to_bool,
    to_int,
)

# 見出し直後のセクション本文として収集する近傍要素数の上限。
# atwiki の見出し直下は数要素（p/div/table 程度）で次セクションに移るため
# 6 要素で十分に本文を覆い、かつ無関係なセクションを巻き込まない。
_SECTION_SIBLING_LIMIT = 6

# 見出し直後から走査するテーブル数の上限（出撃可否表は先頭付近にしか無い）
_TABLE_SCAN_LIMIT = 3


def _section_text(h: Tag) -> str:
    """見出し h の直後に続く近傍要素のテキストを連結して返す。

    次の見出し（h*）に達するか _SECTION_SIBLING_LIMIT 個まで収集する。
    """
    parts: list[str] = []
    cur = h
    for _ in range(_SECTION_SIBLING_LIMIT):
        cur = cur.find_next_sibling()
        if not cur or getattr(cur, "name", "").startswith("h"):
            break
        parts.append(cur.get_text(" ") if hasattr(cur, "get_text") else str(cur))
    return clean_text(" \n ".join(parts))


def _scan_deployment_tables(h: Tag) -> tuple[bool | None, bool | None]:
    """見出し h の近傍テーブルから「地上 | ◯」「宇宙 | ×」形式の可否を読み取る。

    セルを順に見て「地上」「宇宙」を含むセルの直後のセルを可否記号として解釈する
    （表の構造上、ラベルセルの次に値セルが並ぶ前提）。最初に得られた値を優先する。
    """
    ground = None
    space = None
    seen = 0
    cur = h
    while seen < _TABLE_SCAN_LIMIT and cur:
        cur = cur.find_next_sibling()
        if not cur:
            break
        if cur.name != "table":
            continue
        seen += 1
        for tr in cur.find_all("tr"):
            cells = [
                clean_text(x.get_text(" "))
                for x in tr.find_all(["th", "td"])
                if clean_text(x.get_text(" "))
            ]
            if not cells:
                continue
            # 形式1: 地上 | ◯    宇宙 | ×
            for i, c in enumerate(cells):
                if "地上" in c and i + 1 < len(cells):
                    v = symbol_to_bool(cells[i + 1])
                    if v is not None:
                        ground = v if ground is None else ground
                if "宇宙" in c and i + 1 < len(cells):
                    v = symbol_to_bool(cells[i + 1])
                    if v is not None:
                        space = v if space is None else space
    return ground, space


def _find_deployment_headers(soup: BeautifulSoup) -> list[Tag]:
    """出撃可否・環境適正の記載がありそうな見出しを集める。"""
    headers: list[Tag] = []
    for hx in soup.find_all(["h2", "h3", "h4"]):
        txt = clean_text(hx.get_text(" "))
        if any(k in txt for k in ("出撃", "環境適正", "機体属性・出撃制限・環境適正")):
            headers.append(hx)
    return headers


def parse_deployment(soup: BeautifulSoup) -> dict[str, bool | None]:
    """出撃可否（地上/宇宙）を推定して返す。

    - 優先: atwiki 固有 ID label_sortie_{G|n}_{S|n}（G=地上可, S=宇宙可, n=不可）
    - 次点: 「〜出撃のみ」系の明示文
    - 次点: 記号/語（◯/×/可/不可/△）の行や表
    - 何も見つからなければ None
    """
    result: dict[str, bool | None] = {"出撃_地上可": None, "出撃_宇宙可": None}
    # 0) atwiki 固有のIDにエンコードされているケース: label_sortie_{G|n}_{S|n}
    lab = soup.find(id=re.compile(r"^label_sortie_([GSn])_([GSn])$"))
    if lab and hasattr(lab, 'get'):
        m = re.match(r"label_sortie_([GSn])_([GSn])", lab.get('id', ''))
        if m:
            g, s = m.group(1), m.group(2)
            result["出撃_地上可"] = True if g == 'G' else (False if g == 'n' else None)
            result["出撃_宇宙可"] = True if s == 'S' else (False if s == 'n' else None)
            return result
    headers = _find_deployment_headers(soup)
    # 1) 明示文（のみ）
    for h in headers:
        txt = _section_text(h)
        t = txt.replace("：", ":")
        # 地上のみ/宇宙のみ
        if "地上" in t and "のみ" in t:
            result["出撃_地上可"], result["出撃_宇宙可"] = True, False
            return result
        if "宇宙" in t and "のみ" in t:
            result["出撃_地上可"], result["出撃_宇宙可"] = False, True
            return result
    # 2) 記号表記
    for h in headers:
        txt = _section_text(h)
        # パターン: 地上:◯ 宇宙:×
        m1 = re.search(r"地上\s*[:：]\s*([◎◯○〇△×不可可])", txt)
        m2 = re.search(r"宇宙\s*[:：]\s*([◎◯○〇△×不可可])", txt)
        gz = symbol_to_bool(m1.group(1)) if m1 else None
        uz = symbol_to_bool(m2.group(1)) if m2 else None
        if gz is not None or uz is not None:
            result["出撃_地上可"], result["出撃_宇宙可"] = gz, uz
            return result
        # テーブル走査
        tgz, tuz = _scan_deployment_tables(h)
        if tgz is not None or tuz is not None:
            result["出撃_地上可"], result["出撃_宇宙可"] = tgz, tuz
            return result
    return result


def parse_env_suitability(soup: BeautifulSoup) -> dict[str, bool]:
    """環境適正（地上/宇宙/水中）を抽出。見つからないものは False。

    優先: atwiki 固有ID label_env_{G|n}_{S|n}(_{W|n})
    フォールバック: 文言/表からの記号解釈（簡易）
    """
    result = {"環境適正_地上": False, "環境適正_宇宙": False, "環境適正_水中": False}
    # 1) 固有ID
    lab = soup.find(id=re.compile(r"^label_env_([Gn])_([Sn])(?:_([Wn]))?$"))
    if lab and hasattr(lab, "get"):
        m = re.match(r"label_env_([Gn])_([Sn])(?:_([Wn]))?", lab.get("id", ""))
        if m:
            g, s, w = m.group(1), m.group(2), m.group(3)
            result["環境適正_地上"] = g == "G"
            result["環境適正_宇宙"] = s == "S"
            result["環境適正_水中"] = (w == "W") if w is not None else False
            return result

    # 2) テキスト/表（簡易フォールバック）
    headers: list[Tag] = []
    for hx in soup.find_all(["h2", "h3", "h4"]):
        txt = clean_text(hx.get_text(" "))
        if "環境適正" in txt or "機体属性・出撃制限・環境適正" in txt:
            headers.append(hx)
    for h in headers:
        txt = _section_text(h)

        def find_bool(label: str, txt: str = txt) -> bool | None:
            m = re.search(label + r"\s*[:：]\s*([^\s]+)", txt)
            if m:
                return symbol_to_bool(m.group(1))
            return None

        gz = find_bool("地上")
        uz = find_bool("宇宙")
        wz = find_bool("水中")
        if gz is not None:
            result["環境適正_地上"] = bool(gz)
        if uz is not None:
            result["環境適正_宇宙"] = bool(uz)
        if wz is not None:
            result["環境適正_水中"] = bool(wz)
        if gz is not None or uz is not None or wz is not None:
            break
    return result


def extract_title(soup: BeautifulSoup) -> str:
    """ページタイトルから機体名部分を取り出す（例: "F90［MZ仕様］ - 機動戦士..."）。"""
    title = soup.title.get_text(" ") if soup.title else ""
    return title.split(" - ")[0].strip()


def levels_from_table(table: Tag) -> list[int]:
    """ステータステーブルの見出し行から MS レベル一覧（LV1, LV2, ...）を得る。"""
    # 1) thead優先
    thead = table.find("thead")
    headers = []
    if thead:
        headers = [clean_text(th.get_text(" ")) for th in thead.find_all("th")]
    # 2) thead が無い/空なら、最初に LV を含む行の th 群を使う
    if not headers:
        for tr in table.find_all("tr"):
            ths = tr.find_all("th")
            if not ths:
                continue
            texts = [clean_text(th.get_text(" ")) for th in ths]
            if any(re.search(r"LV\d+", t) for t in texts):
                headers = texts
                break
    lv: list[int] = []
    for t in headers[1:]:  # 先頭列は項目名 or 属性名
        m = re.search(r"LV(\d+)", t, re.IGNORECASE)
        if m:
            lv.append(int(m.group(1)))
    return lv


def expand_cells(cells: list[Tag], n_levels: int) -> list[str | None]:
    """td 群を colspan を展開しつつ LV 数に合わせた値リストにする。"""
    vals: list[str | None] = []
    for td in cells:
        colspan = int(td.get("colspan", 1))
        txt = clean_text(td.get_text(" "))
        vals.extend([txt] * colspan)
    # 長すぎる場合は切る、短ければNoneで埋める
    if len(vals) > n_levels:
        vals = vals[:n_levels]
    while len(vals) < n_levels:
        vals.append(None)
    return vals


def find_detail_table(soup: BeautifulSoup) -> tuple[Tag | None, Tag | None]:
    """ステータステーブルとその親 div（属性推定に使う）を探す。

    優先: id="table_{kyoushu|hanyou|sien}" の div 内のテーブル。
    フォールバック: "LV\\d+" を含む最初のテーブル。
    """
    tbl_div = soup.find(id=re.compile(r"^table_(kyoushu|hanyou|sien)$"))
    table = tbl_div.find("table") if tbl_div else None
    if not table:
        for candidate in soup.find_all("table"):
            if candidate.find(string=re.compile(r"LV\d+")):
                table = candidate
                break
    return tbl_div, table


# FIELD_MAP の値のうち、整数化せず文字列のまま保持するフィールド
_TEXT_FIELDS = ("格闘判定力", "カウンター", "レアリティ", "必要階級")


def extract_row_labels(table: Tag | None) -> tuple[list[str], list[str]]:
    """ステータス表の行見出しを (raw, normalized) の重複なしリストで返す。

    ラベル監査（`scrape_msdata labels` → `audit_labels`）用。出現順を保つ。
    """
    raw_labels: list[str] = []
    normalized_labels: list[str] = []
    if table is None:
        return raw_labels, normalized_labels
    seen_raw: set[str] = set()
    seen_norm: set[str] = set()
    for tr in table.find_all("tr"):
        th = tr.find("th")
        if not th:
            continue
        rname = clean_text(th.get_text(" "))
        nname = normalize_row_label(rname)
        if rname and rname not in seen_raw:
            raw_labels.append(rname)
            seen_raw.add(rname)
        if nname and nname not in seen_norm:
            normalized_labels.append(nname)
            seen_norm.add(nname)
    return raw_labels, normalized_labels


def build_base_records(
    table: Tag, name: str, levels: list[int]
) -> dict[int, dict[str, Any]]:
    """ステータステーブルから LV ごとの基本レコードを組み立てる。

    行見出しを FIELD_MAP（core.labels）で正規化キーに変換し、
    数値フィールドは整数化、_TEXT_FIELDS は文字列のまま格納する。
    """
    per_level: dict[int, dict[str, Any]] = {
        lv: {"MS名": f"{name}_LV{lv}"} for lv in levels
    }

    for tr in table.find_all("tr"):
        th = tr.find("th")
        if not th:
            continue
        row_name = clean_text(th.get_text(" "))
        key_name = FIELD_MAP.get(row_name)
        if key_name is None:
            key_name = FIELD_MAP.get(normalize_row_label(row_name))
        if key_name is None:
            continue

        values = expand_cells(tr.find_all("td"), len(levels))
        for lv, val in zip(levels, values, strict=False):
            if val is None:
                continue
            if key_name in _TEXT_FIELDS:
                text = clean_text(val)
                # 新規作成ページではカウンター欄にテンプレートの候補羅列が
                # 残っていることがあるため、未記入として空にする
                if key_name == "カウンター" and is_counter_placeholder(text):
                    text = ""
                # 隣接行のチケット数が必要階級へ誤配置された場合は寄せ替える
                if key_name == "必要階級" and looks_like_ticket_count(text):
                    iv = to_int(text)
                    if iv is not None and "必要リサイクルチケット" not in per_level[lv]:
                        per_level[lv]["必要リサイクルチケット"] = iv
                    text = ""
                per_level[lv][key_name] = text
                continue

            iv = to_int(val)
            if iv is not None:
                per_level[lv][key_name] = iv
    return per_level


def apply_parts_slots(
    soup: BeautifulSoup, per_level: dict[int, dict[str, Any]], levels: list[int]
) -> None:
    """「パーツスロット」見出し直後の表から近/中/遠スロット値を併合する。"""
    parts_table: Tag | None = None
    for h3 in soup.find_all("h3"):
        if "パーツスロット" in h3.get_text():
            parts_table = h3.find_next_sibling("table")
            break

    if not parts_table:
        return

    row_name_map = {
        "近距離": "近スロット",
        "中距離": "中スロット",
        "遠距離": "遠スロット",
    }
    for tr in parts_table.find_all("tr"):
        th = tr.find("th")
        if not th:
            continue
        dst_key = row_name_map.get(clean_text(th.get_text(" ")))
        if not dst_key:
            continue
        values = expand_cells(tr.find_all("td"), len(levels))
        for lv, val in zip(levels, values, strict=False):
            iv = to_int(val or "")
            if iv is not None:
                per_level[lv][dst_key] = iv


def infer_attr_from_table_div(tbl_div: Tag | None) -> str | None:
    """テーブル親 div の id（table_kyoushu 等）から属性名を推定する。"""
    if not tbl_div or not isinstance(tbl_div, Tag):
        return None
    match = re.search(r"table_(kyoushu|hanyou|sien)", tbl_div.get("id", ""))
    if not match:
        return None
    attr_map = {"kyoushu": "強襲", "hanyou": "汎用", "sien": "支援"}
    return attr_map.get(match.group(1))


def apply_attr(
    per_level: dict[int, dict[str, Any]], levels: list[int], attr: str | None
) -> None:
    """全 LV に属性（汎用/強襲/支援）を設定する。"""
    if not attr:
        return
    for lv in levels:
        per_level[lv]["属性"] = attr


def apply_deployment_and_env(
    soup: BeautifulSoup, per_level: dict[int, dict[str, Any]], levels: list[int]
) -> None:
    """出撃可否と環境適正の推定結果を全 LV に併合する。"""
    dep = parse_deployment(soup)
    env = parse_env_suitability(soup)
    for lv in levels:
        for key, value in dep.items():
            if value is not None:
                per_level[lv][key] = value
        per_level[lv].update(env)


def apply_deployment_fallbacks(
    per_level: dict[int, dict[str, Any]], levels: list[int]
) -> None:
    """出撃可否が推定できなかった LV を、旋回値がどちら側にあるかで補完する。

    旋回_地上_通常時 / 旋回_宇宙_通常時 はそれぞれ出撃可能な側にしか
    記載されないため、片側のみ存在する場合は出撃可否の根拠になる。
    """
    for lv in levels:
        rec = per_level[lv]
        if "出撃_地上可" not in rec and "出撃_宇宙可" not in rec:
            has_g = "旋回_地上_通常時" in rec
            has_s = "旋回_宇宙_通常時" in rec
            if has_g and has_s:
                rec["出撃_地上可"] = True
                rec["出撃_宇宙可"] = True
            elif has_g and not has_s:
                rec["出撃_地上可"] = True
                rec["出撃_宇宙可"] = False
            elif has_s and not has_g:
                rec["出撃_地上可"] = False
                rec["出撃_宇宙可"] = True


def normalize_turn_values(
    per_level: dict[int, dict[str, Any]], levels: list[int]
) -> None:
    """片側出撃の機体で、誤った側に入った旋回値を正しい側のキーへ移し替える。

    wiki の表は出撃不可側の旋回列を持たないことがあり、抽出時に
    地上/宇宙の取り違えが起きるため、確定済みの出撃可否で補正する。
    """
    for lv in levels:
        rec = per_level[lv]
        ground = rec.get("出撃_地上可")
        space = rec.get("出撃_宇宙可")
        if ground is False and space is True:
            if "旋回_宇宙_通常時" not in rec and "旋回_地上_通常時" in rec:
                rec["旋回_宇宙_通常時"] = rec.pop("旋回_地上_通常時")
            if "旋回_宇宙_変形時" not in rec and "旋回_地上_変形時" in rec:
                rec["旋回_宇宙_変形時"] = rec.pop("旋回_地上_変形時")
        if ground is True and space is False:
            if "旋回_地上_通常時" not in rec and "旋回_宇宙_通常時" in rec:
                rec["旋回_地上_通常時"] = rec.pop("旋回_宇宙_通常時")
            if "旋回_地上_変形時" not in rec and "旋回_宇宙_変形時" in rec:
                rec["旋回_地上_変形時"] = rec.pop("旋回_宇宙_変形時")


# 完全なレコードとみなすために必須のフィールド群
BASE_REQUIRED = {
    "HP",
    "スピード",
    "スラスター",
    "高速移動",
    "射撃補正",
    "格闘補正",
    "耐ビーム補正",
    "耐実弾補正",
    "耐格闘補正",
    "近スロット",
    "中スロット",
    "遠スロット",
}
# 必須フィールドのうち、欠損時に前 LV の値で補完してよいもの
FALLBACKABLE_REQUIRED_KEYS = {"スラスター"}


def has_turn_value(rec: dict[str, Any]) -> bool:
    """旋回値（地上または宇宙）を持つか。レコード完全性判定の一部。"""
    return ("旋回_地上_通常時" in rec) or ("旋回_宇宙_通常時" in rec)


def apply_required_value_fallbacks(
    per_level: dict[int, dict[str, Any]], levels: list[int]
) -> None:
    """FALLBACKABLE_REQUIRED_KEYS の欠損を前 LV の値で補完する。

    補完するのは「その値以外の必須項目が揃っている」LV のみ。
    表の歯抜け（セル結合崩れ等）で1項目だけ落ちたケースを救済する。
    """
    last_values: dict[str, Any] = {}
    for lv in sorted(levels):
        rec = per_level.get(lv)
        if not isinstance(rec, dict):
            continue

        for key in FALLBACKABLE_REQUIRED_KEYS:
            if key in rec:
                last_values[key] = rec[key]
                continue
            if key not in last_values:
                continue

            required_without_key = BASE_REQUIRED - {key}
            if required_without_key.issubset(rec.keys()) and has_turn_value(rec):
                rec[key] = last_values[key]


def filter_complete_records(
    per_level: dict[int, dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    """必須フィールドと旋回値が揃った LV のレコードだけを残す。"""
    return {
        lv: rec
        for lv, rec in per_level.items()
        if BASE_REQUIRED.issubset(rec.keys()) and has_turn_value(rec)
    }


def parse_details(html: str) -> dict[int, dict[str, Any]]:
    """詳細ページ HTML から LV ごとの正規化済みレコードを抽出する。

    適用順序の依存関係はモジュール docstring を参照。
    """
    soup = BeautifulSoup(html, "lxml")
    name = extract_title(soup)

    tbl_div, table = find_detail_table(soup)
    if not table:
        raise ValueError("機体テーブルが見つかりませんでした")

    levels = levels_from_table(table)
    if not levels:
        raise ValueError("LV 見出しが検出できませんでした")

    per_level = build_base_records(table, name, levels)
    apply_parts_slots(soup, per_level, levels)
    apply_attr(per_level, levels, infer_attr_from_table_div(tbl_div))
    apply_deployment_and_env(soup, per_level, levels)
    apply_deployment_fallbacks(per_level, levels)
    normalize_turn_values(per_level, levels)
    apply_required_value_fallbacks(per_level, levels)
    apply_fullst_fallback(per_level, levels, parse_fullst_by_ms_level(soup, levels))
    return filter_complete_records(per_level)
