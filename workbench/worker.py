"""Managed evaluation process. Replay is offline; collect explicitly calls APIs."""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .domain import MODELS, ROOT, cases, contract_hash, messages, model_cost, money, prices
from .evidence import analyze
from .governance import create_guard, validate


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    os.replace(temp, path)


async def collect(output: Path, budget: Decimal, max_cases: int = 24, workers: int = 3) -> None:
    if output.exists() or output.with_suffix(".partial").exists():
        raise ValueError("output already exists; preserve recordings and choose another path")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY in the environment; it is never stored in this app")
    if budget <= 0 or budget > Decimal("5"):
        raise ValueError("This demo permits a positive API budget up to $5 per run")
    import tiktoken
    from axonllm import build_router
    corpus = cases()[:max_cases]
    encoding = tiktoken.get_encoding("o200k_base")
    planned_bound = Decimal(0)
    for model in MODELS:
        p = prices()["models"][model]
        for case in corpus:
            # Conservative input envelope includes max previous-stage output and
            # formatting. This bounds configured token pricing, not an invoice.
            for stage in ("triage", "draft"):
                tokens = len(encoding.encode(json.dumps(messages(case, stage))))
                input_bound = tokens + 800
                planned_bound += (Decimal(input_bound) * Decimal(p["input"]) +
                                  Decimal(500) * Decimal(p["output"])) / 1_000_000
    if planned_bound > budget:
        raise ValueError(f"Conservative configured-price envelope ${planned_bound} exceeds ${budget}")
    record = {
        "schema": "ai-ops.recording.v1", "mode": "live",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contract_hash": contract_hash(), "samples": [],
        "provenance": {
            "data": "Authored synthetic support tickets",
            "inference": "Actual OpenAI API calls through the pinned AxonLLM public AsyncRouter",
            "governance": "Actual Ostiari Guard, embedded in this managed worker",
            "quality": "Deterministic decision contract checks; no LLM judge",
            "axon_version": importlib.metadata.version("axon-llm"),
            "ostiari_version": importlib.metadata.version("ostiari"),
            "settings": {"temperature": 0, "max_tokens": 500, "retries": 0, "workers": workers},
            "budget_usd": str(budget), "planned_price_envelope_usd": money(planned_bound),
            "prices": prices(), "scope": "No external tool execution or routing deployment",
        },
    }
    guard = create_guard()
    router = build_router(models=ROOT / "config/models.yaml", providers=ROOT / "config/providers.yaml",
                          pricing=ROOT / "config/pricing.yaml", enabled_providers=["openai"],
                          max_retries=0, require_priced_mappings=True)
    semaphore = asyncio.Semaphore(workers)

    async def run(model: str, case: dict) -> None:
        async with semaphore:
            start = time.perf_counter()
            stages, triage = [], ""
            for stage in ("triage", "draft"):
                if validate(guard, "support.draft", {"case_id": case["id"], "model": model,
                                                    "stage": stage})["tier"] != "allow":
                    raise RuntimeError("Ostiari denied the draft-only evaluation")
                request = messages(case, stage, triage)
                call_start = time.perf_counter()
                item = {"name": stage, "messages": request}
                try:
                    response = await router.chat.completions.create(
                        model=model, messages=request, temperature=0, max_tokens=500)
                    usage = asdict(response.usage)
                    item.update({"status": "success", "output": response.choices[0]["message"]["content"],
                                 "usage": usage, "provider_response_id": response.id,
                                 "response_model": response.model,
                                 "estimated_cost_usd": money(model_cost(model, usage))})
                except Exception as exc:
                    # Do not record exception text: provider/transport errors may contain secrets.
                    item.update({"status": "error", "error_type": type(exc).__name__,
                                 "output": "", "usage": None, "estimated_cost_usd": None})
                    attempts = getattr(exc, "attempts", [])
                    item["provider_status_codes"] = [a.get("status_code") for a in attempts]
                    item["error_categories"] = [
                        category for category in ("rate limit", "quota", "model", "timeout",
                                                  "connection", "unauthorized", "capacity", "session")
                        if category in str(exc).lower()
                    ]
                item["latency_ms"] = round((time.perf_counter() - call_start) * 1000, 3)
                stages.append(item)
                if item["status"] != "success":
                    break
                triage = item["output"]
            record["samples"].append({"case_id": case["id"], "model": model, "stages": stages,
                                      "latency_ms": round((time.perf_counter() - start) * 1000, 3)})
            write_json(output.with_suffix(".partial"), record)
            print(f'{len(record["samples"])}/{len(corpus) * len(MODELS)} tasks recorded', flush=True)
    try:
        await asyncio.gather(*(run(model, case) for case in corpus for model in MODELS))
        record["samples"].sort(key=lambda s: (s["model"], s["case_id"]))
        write_json(output, record)
        output.with_suffix(".partial").unlink(missing_ok=True)
    finally:
        await router.close()
        guard.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    replay = sub.add_parser("replay")
    replay.add_argument("recording", type=Path)
    replay.add_argument("--output", type=Path)
    live = sub.add_parser("collect")
    live.add_argument("--output", type=Path, required=True)
    live.add_argument("--budget-usd", type=Decimal, required=True)
    live.add_argument("--max-cases", type=int, choices=range(1, 25), default=24)
    args = parser.parse_args()
    if args.command == "collect":
        asyncio.run(collect(args.output, args.budget_usd, args.max_cases))
    else:
        result = analyze(json.loads(args.recording.read_text()))
        if args.output:
            write_json(args.output, result)
        print(json.dumps({"models": result["models"], "calls": result["total_calls"],
                          "api_estimate_usd": result["total_cost_usd"]}, indent=2))


if __name__ == "__main__":
    main()
