"""Freeze a larger calibration packet and verify baselines without model calls."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from .billing_acceptance import read_json, write_private
from .coding import DATA, DockerRunner, dataset, fingerprint, grades, prompt


def corpus():
    cases = dataset()["cases"] + read_json(DATA / "calibration.json")["cases"]
    # Keep the original six-case fixture/recording hash stable. The expanded
    # calibration makes its string-format acceptance criterion explicit.
    next(case for case in cases if case["id"] == "decimal-charge")["prompt"] = (
        "Return the exact Decimal cost as fixed-point text, never scientific notation: "
        "tokens * USD per million / 1000000. Do not round away small charges.")
    return {"schema": "workbench.coding.calibration.v1", "cases": cases}


def plan(value, *, candidates=3, repetitions=3, seed=20261029):
    if not 2 <= candidates <= 6 or not 1 <= repetitions <= 10:
        raise ValueError("Use 2–6 candidates and 1–10 repetitions")
    ids = [case["id"] for case in value["cases"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate task identity")
    # Shuffle task/repetition blocks; rotate candidate position to distribute order effects.
    rng = random.Random(seed)
    blocks = [(case, rep) for rep in range(1, repetitions + 1) for case in ids]
    rng.shuffle(blocks)
    schedule = []
    for index, (case, repetition) in enumerate(blocks):
        for position in range(candidates):
            schedule.append({"case_id": case, "repetition": repetition,
                             "candidate": f"candidate-{(index + position) % candidates + 1}"})
    return {
        "schema": "workbench.coding.plan.v1", "status": "prepared_no_model_results",
        "dataset_sha256": fingerprint(value), "seed": seed,
        "distinct_tasks": len(ids), "candidates": candidates, "repetitions": repetitions,
        "planned_task_runs": len(schedule), "schedule": schedule,
        "candidate_models": {f"candidate-{n+1}": None for n in range(candidates)},
        "approved_api_budget_usd": None, "price_snapshot": None,
        "max_attempts_per_task": 2, "model_calls": 0,
        "hardware_and_electricity_cost_usd": None,
        "limitations": [
            "Authored public calibration tasks; repetitions are not independent tasks.",
            "Prompt packets omit references and acceptance tests, which remain public in the repository.",
            "Freeze representative private holdout tasks before a publication-quality comparison.",
            "The packet has no model results. Collect with --dataset and --repetitions, then evaluate the version 2 recording before previewing it.",
            "Choose exact models, dated prices, independent holdout, credentials and budget before collection.",
        ],
    }


def verify_baselines(value, runner):
    rows = []
    for case in value["cases"]:
        tests = case["public_tests"] + case["acceptance_tests"]
        broken = runner.run(case["source"], [test["input"] for test in tests])
        reference = runner.run(case["reference"], [test["input"] for test in tests])
        broken_grades, reference_grades = grades(broken, tests), grades(reference, tests)
        if not all(reference_grades) or all(broken_grades):
            raise ValueError("Calibration baseline does not distinguish the broken and reference implementations")
        rows.append({"case_id": case["id"], "tests": len(tests),
                     "broken_passed": sum(broken_grades), "reference_passed": sum(reference_grades),
                     "broken_status": broken["status"], "reference_status": reference["status"],
                     "test_duration_ms": round(broken["duration_ms"] + reference["duration_ms"], 3)})
    return {"schema": "workbench.coding.calibration-check.v1",
            "status": "offline_baselines_passed", "dataset_sha256": fingerprint(value),
            "image_id": runner.image, "cases": rows, "model_calls": 0,
            "external_api_cost_usd": "0", "hardware_and_electricity_cost_usd": None,
            "notice": "Container outcomes for authored patches; no measured model performance."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--candidates", type=int, default=3)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--image", help="Locally pulled Python Docker image; enables isolated baseline execution")
    args = parser.parse_args()
    try:
        value = corpus()
        document = plan(value, candidates=args.candidates, repetitions=args.repetitions, seed=args.seed)
        args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        write_private(args.output_dir / "plan.json", document)
        write_private(args.output_dir / "prompts.json", {case["id"]: prompt(case) for case in value["cases"]})
        write_private(args.output_dir / "operator-dataset.json", value)
        if args.image:
            receipt = verify_baselines(value, DockerRunner(args.image))
            write_private(args.output_dir / "baseline-check.json", receipt)
        print(json.dumps({key: document[key] for key in (
            "status", "distinct_tasks", "candidates", "repetitions", "planned_task_runs", "model_calls")}))
    except (OSError, ValueError, RuntimeError):
        parser.exit(1, "Preparation failed. Preserve existing packets, use a new output directory and verify Docker baselines.\n")


if __name__ == "__main__":
    main()
