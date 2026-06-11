#!/usr/bin/env python3
"""
JSONLファイルをJSON配列に変換するユーティリティ（uv 前提）。

機能
- JSONLファイル（各行がJSONオブジェクト）を読み込み、JSON配列に変換
- エラーハンドリングと進捗表示を含む

使用例
- 変換: uv run python -m ms_data.pipeline.jsonl_to_json cache/details.jsonl cache/details.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="JSONLファイルをJSON配列に変換")
    parser.add_argument(
        "input",
        type=str,
        help="入力JSONLファイルのパス",
    )
    parser.add_argument(
        "output",
        type=str,
        help="出力JSONファイルのパス",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    # 入力ファイルの存在確認
    if not input_path.exists():
        print(f"Error: 入力ファイルが見つかりません: {input_path}", file=sys.stderr)
        return 1

    # JSONLを読み込み
    records: list[Any] = []
    try:
        with input_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    records.append(record)
                except json.JSONDecodeError as e:
                    print(
                        f"Warning: 行 {line_num} のJSON解析に失敗しました: {e}",
                        file=sys.stderr,
                    )
                    continue
    except Exception as e:
        print(f"Error: ファイル読み込みエラー: {e}", file=sys.stderr)
        return 1

    # JSON配列として出力
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"Converted {len(records)} records to {output_path}")
        return 0
    except Exception as e:
        print(f"Error: ファイル書き込みエラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
