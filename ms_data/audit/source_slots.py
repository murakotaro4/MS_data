"""取得元スロットの限定的な異常検知と、機体＋LV単位の部分保留。

正解値は推測しない。原値は補正前に監査し、既存の全体検証は隔離で隠さない。
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ms_data.core import paths
from ms_data.core.dates import JST
from ms_data.core.json_io import load_json
from ms_data.core.ms_names import MS_NAME_WITH_LEVEL
from ms_data.gh.outputs import append_step_summary, write_github_output
from ms_data.pipeline.official_overrides import (
    OfficialOverrideValue,
    apply_official_overrides,
    override_is_active,
)
from ms_data.reporting.rendering import append_table, value_text
from ms_data.validation.validate_msdata import (
    find_semantic_errors,
    validate_schema,
)

Records = dict[str, dict[str, Any]]
Overrides = dict[str, dict[str, OfficialOverrideValue]]
SLOTS = ("近スロット", "中スロット", "遠スロット")
SCHEMA_PATH = Path(__file__).resolve().parents[2] / paths.MSDATA_SCHEMA


def empty_audit() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "ok",
        "held_record_count": 0,
        "approved_record_count": 0,
        "fallback_corrected_record_count": 0,
        "previous_unverified_count": 0,
        "findings": [],
        "global_errors": [],
    }


def _complete_slots(record: dict[str, Any]) -> bool:
    return all(type(record.get(k)) is int and record[k] >= 0 for k in SLOTS)


def detect_anomalies(records: Records) -> list[dict[str, Any]]:
    """連続LV・コスト+50の内点で、単一スロットの谷かつ合計低下を検出。

    形態を含む基底名・属性・URLを完全一致させる。端点や欠損では推定しない。
    スロット配分変更だけで合計が増える正常例は保留しない。
    """
    groups: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = {}
    for name, record in records.items():
        match = MS_NAME_WITH_LEVEL.fullmatch(name)
        attr, url = record.get("属性"), record.get("wiki_url")
        if not match or attr not in {"汎用", "強襲", "支援"} or not url:
            continue
        if not isinstance(url, str) or not _complete_slots(record):
            continue
        if type(record.get("コスト")) is not int:
            continue
        key = (match["base"], attr, url)
        groups.setdefault(key, {})[int(match["level"])] = record

    findings: list[dict[str, Any]] = []
    for levels in groups.values():
        for level, current in sorted(levels.items()):
            lower, upper = levels.get(level - 1), levels.get(level + 1)
            if lower is None or upper is None:
                continue
            if not (
                current["コスト"] == lower["コスト"] + 50
                and upper["コスト"] == current["コスト"] + 50
            ):
                continue
            totals = [sum(r[k] for k in SLOTS) for r in (lower, current, upper)]
            for field in SLOTS:
                if current[field] >= min(lower[field], upper[field]):
                    continue
                if totals[1] >= totals[0]:
                    continue
                findings.append(
                    {
                        "MS名": current["MS名"],
                        "level": level,
                        "field": field,
                        "observed": current[field],
                        "comparison": {
                            lower["MS名"]: lower[field],
                            upper["MS名"]: upper[field],
                        },
                        "slot_totals": totals,
                        "wiki_url": current["wiki_url"],
                        "reason": "LV内点のスロット谷かつ下位LVより合計低下",
                    }
                )
    return sorted(findings, key=lambda row: (row["MS名"], row["field"]))


def _known_bad(record: dict[str, Any], specs: dict[str, OfficialOverrideValue]) -> bool:
    return any(
        spec.get("source_error_confirmed")
        and record.get(field) == spec.get("stale_value")
        and spec.get("stale_value") != spec["value"]
        for field, spec in specs.items()
    )


def quarantine_sources(
    previous: Records,
    incoming: Records,
    overrides: Overrides,
    *,
    today: date,
) -> tuple[Records, dict[str, Any]]:
    """候補全体を検証してから、未承認の異常レコードだけ更新を保留する。"""
    raw = deepcopy(incoming)
    candidate = deepcopy({**previous, **incoming})
    apply_official_overrides(candidate, overrides, today=today)
    raw_context = {**previous, **raw}
    rows = [r for r in detect_anomalies(raw_context) if r["MS名"] in raw]
    keys = {(r["MS名"], r["field"]) for r in rows}
    # 本人確認済みの誤値は、隣接欠損・周囲の更新・期限後でも再採用しない。
    for name, record in raw.items():
        for field, spec in overrides.get(name, {}).items():
            if not spec.get("source_error_confirmed"):
                continue
            if record.get(field) != spec.get("stale_value"):
                continue
            if spec["value"] == spec.get("stale_value") or (name, field) in keys:
                continue
            match = MS_NAME_WITH_LEVEL.fullmatch(name)
            rows.append(
                {
                    "MS名": name,
                    "level": int(match["level"]) if match else None,
                    "field": field,
                    "observed": record.get(field),
                    "comparison": {},
                    "slot_totals": [],
                    "wiki_url": record.get("wiki_url", ""),
                    "reason": "本人確認済みの取得元誤値（隣接比較の可否によらず保留）",
                }
            )

    audit = empty_audit()
    audit["audited_at"] = datetime.now(JST).isoformat()
    # 隔離によってschema/意味エラーや従来のprotected rollbackを隠さない。
    values = list(candidate.values())
    errors = validate_schema(values, SCHEMA_PATH) + find_semantic_errors(values)
    legacy_rollbacks = [
        f"{name}: {field}: protected rollback"
        for name, specs in overrides.items()
        for field, spec in specs.items()
        if not spec.get("source_error_confirmed")
        and name in candidate
        and candidate[name].get(field) == spec.get("stale_value")
        and spec.get("stale_value") != spec["value"]
    ]
    audit["global_errors"] = errors + legacy_rollbacks
    if audit["global_errors"]:
        audit["status"] = "global_validation_error"
        for row in rows:
            row["action"] = "global_safety_stop_not_quarantined"
        audit["findings"] = rows
        return candidate, audit

    corrected_bad = {(r["MS名"], r["field"]) for r in detect_anomalies(candidate)}
    old_bad = {r["MS名"] for r in detect_anomalies(previous)}
    fallback = deepcopy(previous)
    apply_official_overrides(fallback, overrides, today=today)
    fallback_bad = {r["MS名"] for r in detect_anomalies(fallback)}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_name.setdefault(row["MS名"], []).append(row)

    for name, findings in sorted(by_name.items()):
        specs = overrides.get(name, {})
        prior = previous.get(name)
        # 旧データでは比較不能でも、今回の比較可能な隣接LVで前値の異常が判明する。
        if prior and any(
            r["MS名"] == name for r in detect_anomalies({**candidate, name: prior})
        ):
            old_bad.add(name)
        old = fallback.get(name)
        if old and any(
            r["MS名"] == name for r in detect_anomalies({**candidate, name: old})
        ):
            fallback_bad.add(name)
        approved = all(
            row["field"] in specs
            and override_is_active(specs[row["field"]], today)
            and row["observed"] == specs[row["field"]].get("stale_value")
            and candidate[name].get(row["field"]) == specs[row["field"]]["value"]
            and (
                (name, row["field"]) not in corrected_bad
                or specs[row["field"]].get("allow_source_anomaly") is True
            )
            for row in findings
        )
        prior_state = "missing"
        if prior:
            prior_state = (
                "known_invalid"
                if _known_bad(prior, specs)
                else "unverified" if name in old_bad else "previously_adopted"
            )
        fallback_corrections: dict[str, dict[str, Any]] = {}
        if approved:
            action = "approved_override"
            audit["approved_record_count"] += 1
        else:
            audit["held_record_count"] += 1
            trusted = bool(
                old
                and name not in fallback_bad
                and not _known_bad(old, specs)
                and not validate_schema([old], SCHEMA_PATH)
                and not find_semantic_errors([old])
                and all(old.get(k) == raw[name].get(k) for k in ("属性", "wiki_url"))
            )
            if trusted:
                candidate[name] = old
                fallback_corrections = {
                    field: {
                        "previous": prior.get(field),
                        "adopted": old.get(field),
                        "expires_after": spec.get("expires_after", ""),
                    }
                    for field, spec in specs.items()
                    if prior.get(field) != old.get(field)
                }
                if fallback_corrections:
                    action = "retained_previous_with_approved_correction"
                    audit["fallback_corrected_record_count"] += 1
                else:
                    action = "retained_previous"
            elif prior:
                # 公開済みの値を推測修正・削除しない。正常保持とは明確に区別。
                candidate[name] = deepcopy(prior)
                action = "previous_unverified_retained"
                audit["previous_unverified_count"] += 1
            else:
                candidate.pop(name, None)
                action = "skipped_new_record"
        for row in findings:
            spec = specs.get(row["field"], {})
            row.update(
                action=action,
                fallback_corrections=fallback_corrections,
                previous_state=prior_state,
                previous=prior.get(row["field"]) if prior else None,
                adopted=candidate.get(name, {}).get(row["field"]),
                confirmed_value=(
                    spec.get("value") if spec.get("source_error_confirmed") else None
                ),
                expires_after=spec.get("expires_after", ""),
                override_expired=bool(spec and not override_is_active(spec, today)),
                source_classification=(
                    "本人確認済みの取得元誤記"
                    if spec.get("source_error_confirmed")
                    else "取得元の誤記疑い・正解未確定（解析原本の確認が必要）"
                ),
            )
    audit["findings"] = sorted(rows, key=lambda r: (r["MS名"], r["field"]))
    if audit["held_record_count"]:
        audit["status"] = "partial_hold"
    elif audit["approved_record_count"]:
        audit["status"] = "approved_correction"
    return candidate, audit


def render_markdown(audit: dict[str, Any]) -> str:
    lines = ["# 取得元スロット監査", "", "## 取得元スロット監査", ""]
    for key in (
        "status",
        "held_record_count",
        "approved_record_count",
        "fallback_corrected_record_count",
        "previous_unverified_count",
    ):
        lines.append(f"- {key}: {audit.get(key, 0)}")
    lines += [
        "",
        "未承認異常は対象機体＋LV全体だけ更新を保留し、他レコードは通常継続します。",
        "previous_unverified_retained は正常な前値なし・既存値も未確認／要対応です。",
        "期限切れで22等を保持した場合は再補正ではなく前値保持です。",
        "retained_previous_with_approved_correction は取得候補を保留し、承認済み補正で前値を修復して保持した状態です。",
        "一般のLV比較だけでは取得元誤記と解析バグを確定できません。",
        "",
        "## 部分保留エラー・補正証拠",
        "",
    ]
    append_table(
        lines,
        [
            "MS名",
            "LV",
            "項目",
            "元値",
            "比較値",
            "前値",
            "採用値",
            "前値の承認修復",
            "処置",
            "前値状態",
            "期限",
            "取得時刻",
            "WikiURL",
            "理由",
        ],
        (
            [
                r["MS名"],
                value_text(r["level"]),
                r["field"],
                value_text(r["observed"]),
                value_text(r["comparison"]),
                value_text(r.get("previous")),
                value_text(r.get("adopted")),
                value_text(r.get("fallback_corrections", {})),
                r["action"],
                r.get("previous_state", ""),
                r.get("expires_after", "")
                + ("（失効）" if r.get("override_expired") else ""),
                r.get("fetched_at") or "未確認",
                r["wiki_url"],
                r.get("source_classification", "") + " / " + r["reason"],
            ]
            for r in audit["findings"]
        ),
    )
    if audit["global_errors"]:
        lines += ["", "## 既存の全体安全停止", *audit["global_errors"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--step-summary", type=Path)
    args = parser.parse_args(argv)
    audit = load_json(args.audit_json)
    text = render_markdown(audit)
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(text, encoding="utf-8")
    if args.github_output:
        write_github_output(
            args.github_output,
            {
                "held_record_count": audit["held_record_count"],
                "finding_count": len(audit["findings"]),
                "status": audit["status"],
            },
        )
    append_step_summary(text.splitlines(), args.step_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
