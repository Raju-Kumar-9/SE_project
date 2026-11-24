"""Evaluate extraction quality, unsupported requirements, and SDLC rankings.

Input files are JSONL. Gold and prediction rows are paired by scenario_id.
Requirement matching uses the same source slot and token F1 >= 0.5, greedily
one-to-one, so duplicate predictions cannot earn duplicate credit.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            scenario_id = row.get("scenario_id")
            if not scenario_id or scenario_id in rows:
                raise ValueError(f"{path}:{line_number}: scenario_id is missing or duplicated")
            rows[scenario_id] = row
    return rows


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def token_f1(left: str, right: str) -> float:
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    common = len(a & b)
    precision, recall = common / len(a), common / len(b)
    return 2 * precision * recall / (precision + recall) if common else 0.0


def match_requirements(gold: list[dict], predicted: list[dict], threshold: float = 0.5) -> tuple[int, int, int]:
    candidates = []
    for gi, expected in enumerate(gold):
        for pi, actual in enumerate(predicted):
            if expected.get("source_slot") != actual.get("source_slot"):
                continue
            similarity = token_f1(str(expected.get("statement", "")), str(actual.get("statement", "")))
            if similarity >= threshold:
                candidates.append((similarity, gi, pi))
    used_gold: set[int] = set()
    used_predicted: set[int] = set()
    for _, gi, pi in sorted(candidates, reverse=True):
        if gi not in used_gold and pi not in used_predicted:
            used_gold.add(gi)
            used_predicted.add(pi)
    return len(used_predicted), len(predicted) - len(used_predicted), len(gold) - len(used_gold)


def kendall_tau(gold_order: list[str], predicted_order: list[str]) -> float | None:
    common = [name for name in gold_order if name in predicted_order]
    if len(common) < 2:
        return None
    predicted_rank = {name: index for index, name in enumerate(predicted_order)}
    concordant = discordant = 0
    for i, left in enumerate(common):
        for right in common[i + 1:]:
            if predicted_rank[left] < predicted_rank[right]:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total else None


def evaluate(gold_rows: dict[str, dict], prediction_rows: dict[str, dict], threshold: float = 0.5) -> dict[str, Any]:
    absent = sorted(set(gold_rows) - set(prediction_rows))
    extra = sorted(set(prediction_rows) - set(gold_rows))
    if absent or extra:
        raise ValueError(f"Scenario mismatch; missing predictions={absent}, unknown predictions={extra}")

    tp = fp = fn = hallucinations = predicted_total = 0
    top1_correct = sdlc_total = 0
    taus = []
    for scenario_id, gold_row in gold_rows.items():
        actual = prediction_rows[scenario_id]
        gold_requirements = gold_row.get("requirements", [])
        predicted_requirements = actual.get("requirements", [])
        matched, false_positive, false_negative = match_requirements(gold_requirements, predicted_requirements, threshold)
        tp += matched
        fp += false_positive
        fn += false_negative
        predicted_total += len(predicted_requirements)
        # An unmatched requirement is operationally an unsupported claim; this
        # metric is a proxy unless benchmark rows separately adjudicate support.
        hallucinations += false_positive

        expected = gold_row.get("sdlc_ranking", [])
        ranking = actual.get("sdlc_recommendation", {}).get("ranked_scores", [])
        predicted_order = [str(row.get("model")) for row in ranking]
        if expected and predicted_order:
            sdlc_total += 1
            top1_correct += int(predicted_order[0] == expected[0])
            tau = kendall_tau(expected, predicted_order)
            if tau is not None:
                taus.append(tau)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "scenarios": len(gold_rows),
        "extraction": {
            "true_positive": tp, "false_positive": fp, "false_negative": fn,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
            "match_threshold": threshold,
        },
        "hallucination_proxy": {
            "unmatched_prediction_rate": round(hallucinations / predicted_total, 4) if predicted_total else 0.0,
            "unmatched_predictions": hallucinations,
            "predictions": predicted_total,
            "definition": "Unmatched requirements are treated as unsupported; manually adjudicate before calling this a true hallucination rate.",
        },
        "sdlc": {
            "top1_accuracy": round(top1_correct / sdlc_total, 4) if sdlc_total else None,
            "top1_correct": top1_correct, "scenarios_scored": sdlc_total,
            "mean_kendall_tau": round(sum(taus) / len(taus), 4) if taus else None,
            "ranking_scenarios_with_tau": len(taus),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True, help="Hand-labeled benchmark JSONL")
    parser.add_argument("--predictions", type=Path, required=True, help="Pipeline output JSONL")
    parser.add_argument("--output", type=Path, help="Optional path for the metrics JSON")
    parser.add_argument("--match-threshold", type=float, default=0.5)
    args = parser.parse_args()
    metrics = evaluate(read_jsonl(args.gold), read_jsonl(args.predictions), args.match_threshold)
    rendered = json.dumps(metrics, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
