"""通知本文（Markdown）の節・表・箇条書きを読み取る共通処理。"""

from __future__ import annotations

import re

_MD_UNESCAPE = re.compile(r"\\([\\`*_\[\]()#+\-.!|<>])")


def _plain(text: str) -> str:
    return _MD_UNESCAPE.sub(r"\1", text)


def _sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"": []}
    heading = ""
    for line in lines:
        if line.startswith("## "):
            heading = line[3:]
            sections.setdefault(heading, [])
        else:
            sections[heading].append(line)
    return sections


def _cells(line: str) -> list[str]:
    # 生成元は '\\|' と '\\\\' をエスケープする。後者の直後の区切りも扱う。
    cells = re.split(r"(?<!\\)((?:\\\\)*)\|", line.strip()[1:-1])
    # re.split のキャプチャ（区切り直前のバックスラッシュ対）を元セルへ戻す。
    values = [cells[0]]
    for index in range(1, len(cells), 2):
        values[-1] += cells[index]
        values.append(cells[index + 1])
    return [_plain(value.strip()) for value in values]


_FULLST_HEADERS = [
    "変更前 No",
    "変更後 No",
    "名称",
    "Lv",
    "変更前 points",
    "変更後 points",
]
ENHANCEMENT_HEADERS = ["強化項目・強化Lv", "変更前", "変更後"]


def _md_row(cells: list[str]) -> str:
    return (
        "| "
        + " | ".join(cell.replace("\\", "\\\\").replace("|", "\\|") for cell in cells)
        + " |"
    )


def _enhancement_value(no: str, point: str, moved: bool) -> str:
    if not no:
        return "項目なし"
    text = "値なし" if point == "null" else point or "未設定"
    return f"{text}（順序{no}）" if moved else text


def enhancement_lines(lines: list[str]) -> list[str]:
    """通知だけで強化明細を左右比較へ変換する。未知形式は原文を残す。"""
    result: list[str] = []
    # 機体ごとに変換し、同じLVを持つ別機体の件数サマリを消さない。
    starts = [
        0,
        *[i for i, line in enumerate(lines) if line.startswith("### ")],
        len(lines),
    ]
    for start, end in zip(starts, starts[1:], strict=False):
        group = lines[start:end]
        converted: dict[int, tuple[int, list[str]]] = {}
        levels: set[str] = set()
        for index, line in enumerate(group):
            match = re.fullmatch(r"(LV\d+) fullst 明細（変更後No順）:", line.strip())
            if not match or index + 2 >= len(group):
                continue
            if _cells(group[index + 1]) != _FULLST_HEADERS or not re.fullmatch(
                r"[| :\-]+", group[index + 2].strip()
            ):
                continue
            stop = index + 3
            rows = []
            while stop < len(group) and group[stop].strip().startswith("|"):
                rows.append(_cells(group[stop]))
                stop += 1
            if not rows or any(
                len(row) != 6
                or not (row[0] or row[1])
                or any(no and not no.isdecimal() for no in row[:2])
                or (not row[0] and bool(row[4]))
                or (not row[1] and bool(row[5]))
                for row in rows
            ):
                continue
            comparison = [
                f"機体{match[1]} 強化項目の必要強化値（変更後の順序／削除項目は末尾）:",
                "値なし = 必要強化値の数値記録なし（未掲載・空欄・補完等）。未設定 = 必要強化値の項目が未設定。項目なし = 強化項目の追加・削除。",
                _md_row(ENHANCEMENT_HEADERS),
                "| --- | --- | --- |",
            ]
            for old_no, new_no, name, level, before, after in rows:
                moved = old_no != new_no

                comparison.append(
                    _md_row(
                        [
                            f"{name}（強化Lv{level}）",
                            _enhancement_value(old_no, before, moved),
                            _enhancement_value(new_no, after, moved),
                        ]
                    )
                )
            converted[index] = (stop, comparison)
            levels.add(match[1])
        index = 0
        while index < len(group):
            if index in converted:
                stop, comparison = converted[index]
                result.extend(comparison)
                index = stop
                continue
            line = group[index]
            if line.strip().startswith("|"):
                cells = _cells(line)
                if len(cells) == 4 and cells[0] in levels and cells[1] == "fullst":
                    index += 1
                    continue
                if cells and cells[0] == "LV" and "fullst" in cells:
                    line = _md_row(
                        ["強化項目数" if cell == "fullst" else cell for cell in cells]
                    )
            result.append(line)
            index += 1
    return result


def _facts(lines: list[str]) -> dict[str, str]:
    return dict(
        line[2:].split(": ", 1)
        for line in lines
        if line.startswith("- ") and ": " in line
    )


def _count(value: str | None) -> int | None:
    return int(value) if value is not None and re.fullmatch(r"\d+", value) else None
