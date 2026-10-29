"""Explicit, bounded OpenAI coding recordings through the existing AxonLLM router."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from .billing_acceptance import write_private
from .coding import DockerRunner, dataset, fingerprint, grades, prompt, verify_recording, validate_dataset
from .domain import MODELS, ROOT, model_cost, money, prices

MAX_OUTPUT_TOKENS = 1024
MAX_REQUEST_TOKENS = 12_000


def planned_envelope(models, cases, attempts, pricebook):
    return sum((Decimal(MAX_REQUEST_TOKENS) * Decimal(pricebook["models"][model]["input"]) +
                Decimal(MAX_OUTPUT_TOKENS) * Decimal(pricebook["models"][model]["output"])
                for model in models), Decimal(0)) * cases * attempts / Decimal(1_000_000)


def freeze_schedule(cases, models, repetitions, seed):
    from .coding_prepare import plan
    if len(models) == 1:
        return [{"candidate": models[0], "case_id": case["id"], "repetition": repetition}
                for repetition in range(1, repetitions + 1) for case in cases["cases"]]
    prepared = plan(cases, candidates=len(models), repetitions=repetitions, seed=seed)
    return [row | {"candidate": models[int(row["candidate"].split("-")[-1]) - 1]}
            for row in prepared["schedule"]]


async def collect(output, models, budget, max_attempts, runner, *, router=None, encoding=None,
                  case_data=None, repetitions=1, seed=20261029):
    """All candidates receive the same snapshots; repair feedback uses public tests only."""
    if output.exists() or output.with_suffix(".partial.json").exists():
        raise ValueError("Choose a new output path; recordings are never overwritten")
    if not models or len(set(models)) != len(models) or not set(models) <= set(MODELS):
        raise ValueError("Choose unique model IDs from the pinned Workbench model configuration")
    if not budget.is_finite() or not Decimal(0) < budget <= Decimal(5) or not 1 <= max_attempts <= 3:
        raise ValueError("Use a positive configured-price budget up to USD 5 and at most three attempts")
    if type(repetitions) is not int or not 1 <= repetitions <= 10:
        raise ValueError("Use one to ten repetitions")
    if case_data is None:
        from .coding_prepare import corpus
        cases = dataset()
        corrected = {case["id"]: case for case in corpus()["cases"]}
        cases["cases"] = [corrected[case["id"]] for case in cases["cases"]]
    else:
        cases = case_data
    cases = validate_dataset(cases)
    schedule = freeze_schedule(cases, models, repetitions, seed)
    if len(schedule) > 1000:
        raise ValueError("Coding run exceeds the sample limit")
    pricebook = prices()
    envelope = planned_envelope(models, len(cases["cases"]) * repetitions, max_attempts, pricebook)
    if envelope > budget:
        raise ValueError("Planned configured-price envelope exceeds the budget")
    from .coding_prepare import verify_baselines
    verify_baselines(cases, runner)
    own_router = router is None
    if own_router:
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("Set OPENAI_API_KEY privately; it is not written to recordings")
        from axonllm import build_router
        router = build_router(models=ROOT / "config/models.yaml", providers=ROOT / "config/providers.yaml",
                              pricing=ROOT / "config/pricing.yaml", enabled_providers=["openai"],
                              max_retries=0, require_priced_mappings=True)
    if encoding is None:
        import tiktoken
        encoding = tiktoken.get_encoding("o200k_base")
    record = {
        "schema": "workbench.coding.recording.v2", "mode": "recorded",
        "dataset_sha256": fingerprint(cases),
        "provenance": (
            "Actual OpenAI calls through the pinned AxonLLM router; sequential attempts, temperature 0, "
            f"max output {MAX_OUTPUT_TOKENS}, retries 0. Private workload, no coding-tool subscription connector. "
            f"Configured-price envelope USD {envelope}; budget USD {budget}; "
            f"pricebook SHA-256 {fingerprint(pricebook)}; schedule SHA-256 {fingerprint(schedule)}; seed {seed}. "
            "Review the bundled rates before use; this is not an invoice spending cap."
        ),
        "samples": [],
    }
    record.update(dataset=cases, planned_samples=schedule)
    partial = output.with_suffix(".partial.json")
    by_id = {case["id"]: case for case in cases["cases"]}
    try:
        for planned in schedule:
            model, case = planned["candidate"], by_id[planned["case_id"]]
            start = time.monotonic()
            messages = [
                {"role": "system", "content": "Fix the supplied Python function. Return only solution.py contents; no markdown. You cannot change tests or install dependencies."},
                {"role": "user", "content": json.dumps(prompt(case))},
            ]
            sample = {"candidate": model, "case_id": case["id"], "repetition": planned["repetition"], "attempts": [],
                      "observed_end_to_end_duration_ms": None}
            record["samples"].append(sample)
            source = case["source"]
            for index in range(max_attempts):
                if len(encoding.encode(json.dumps(messages))) + 1000 > MAX_REQUEST_TOKENS:
                    raise ValueError("Request exceeds the conservative configured-price input envelope")
                call_start = time.monotonic()
                call = {"response_id": "failed-" + uuid.uuid4().hex, "input_tokens": None,
                        "output_tokens": None, "cached_input_tokens": None,
                        "api_estimate_usd": None, "cost_basis": "unknown", "latency_ms": None}
                attempt = {"replacement": source, "calls": [call],
                           "other_tool_api_usd": "0", "human_review_ms": None}
                sample["attempts"].append(attempt)
                # Persist unknown in-flight cost before dispatch, so an
                # interrupted process cannot silently omit this attempt.
                write_private(partial, record)
                failed = False
                try:
                    response = await router.chat.completions.create(
                        model=model, messages=messages, temperature=0, max_tokens=MAX_OUTPUT_TOKENS)
                    usage = asdict(response.usage)
                    call.update(response_id=response.id, input_tokens=usage["prompt_tokens"],
                                output_tokens=usage["completion_tokens"], cached_input_tokens=usage.get("cached_tokens", 0),
                                response_model=response.model)
                    # Never price an unexpected routed model with the
                    # requested model's rate or attribute it silently.
                    if response.model != model:
                        failed = True
                    else:
                        call.update(api_estimate_usd=money(model_cost(model, usage)),
                                    cost_basis="recorded_estimate")
                    candidate = response.choices[0]["message"]["content"]
                    if not isinstance(candidate, str) or not 1 <= len(candidate) <= 32_000:
                        failed = True
                    elif not failed:
                        source = candidate
                except Exception:
                    # A failed/partial provider request may have a cost: preserve unknown.
                    failed = True
                call["latency_ms"] = round((time.monotonic() - call_start) * 1000, 3)
                attempt["replacement"] = source
                write_private(partial, record)
                if failed:
                    break
                public = case["public_tests"]
                checked = grades(runner.run(source, [test["input"] for test in public]), public)
                if all(checked):
                    break
                messages.extend([
                    {"role": "assistant", "content": source},
                    {"role": "user", "content": f"Public tests passed {sum(checked)}/{len(checked)}. Repair the function and return its complete contents."},
                ])
            sample["observed_end_to_end_duration_ms"] = round((time.monotonic() - start) * 1000, 3)
            write_private(partial, record)
            if failed:
                # Stop a paid run when attribution/cost is unknown.
                # Preserve the full schedule so missing runs cannot look complete.
                break
        verify_recording(record)
        write_private(output, record)
        partial.unlink(missing_ok=True)
    finally:
        if own_router:
            await router.close()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", action="append", choices=MODELS, required=True)
    parser.add_argument("--budget-usd", type=Decimal, required=True)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--image", required=True)
    parser.add_argument("--dataset", type=Path, help="Frozen operator dataset from the preparation packet")
    parser.add_argument("--repetitions", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--allow-model-calls", action="store_true", required=True)
    args = parser.parse_args()
    try:
        from .billing_acceptance import read_json
        cases = read_json(args.dataset, 4_000_000) if args.dataset else None
        asyncio.run(collect(args.output, args.model, args.budget_usd, args.max_attempts, DockerRunner(args.image),
                            case_data=cases, repetitions=args.repetitions, seed=args.seed))
    except (OSError, ValueError, RuntimeError):
        parser.exit(1, "Recording failed. Check the private key, model access, budget, Docker image, and partial recording.\n")
    print("Coding model recording saved privately. Run the offline evaluator to check acceptance tests.")


if __name__ == "__main__":
    main()
