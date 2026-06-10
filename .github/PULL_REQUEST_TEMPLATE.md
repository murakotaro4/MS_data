## 概要
<!-- 何を、なぜ、どう変えたか（1〜3行） -->

## 変更点
<!-- スキーマ変更 / 抽出ロジック / 補正 / ドキュメント など箇条書き -->

## データ来歴（必要に応じて）
<!-- 取得日・ソースURL・処理コマンド -->

## 検証結果
<!-- `uv run python -m ms_data.tasks validate-strict` の結果、差分統計 `records: A -> B | +X -Y ~Z` など -->

## 影響範囲 / 後方互換性

## チェックリスト
- [ ] `uv run black .` / `uv run ruff check .` を通過
- [ ] `uv run pytest -q` を通過
- [ ] `uv run python -m ms_data.tasks validate-strict` を通過
- [ ] 差分の件数 / 要点を PR に記載
