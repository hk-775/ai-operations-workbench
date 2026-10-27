"""A two-step Bedrock task. Default: synthetic metadata, no AWS calls."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workbench.bedrock import capture_converse, capture_converse_stream
from workbench.connector import Outbox
from workbench.pilot.events import BedrockContext, BedrockUsage, BedrockUsageEvent


def seed_fixture(outbox):
    for stage, inputs, outputs in (("classify", 1000, 100), ("draft", 1500, 200)):
        outbox.put(BedrockUsageEvent(schema_version="bedrock.usage.v1",
            event_id=f"bedrock-fixture-v1:{stage}", task_id="bedrock-fixture-v1",
            project="bedrock-example", stage=stage, model="amazon.nova-micro-v1:0",
            occurred_at="2026-10-27T00:00:00Z", status="success", evidence="fixture",
            usage_basis="provider_reported", attempt_coverage="single_attempt", latency_ms=100.0,
            usage=BedrockUsage(input_tokens=inputs, output_tokens=outputs, total_tokens=inputs+outputs),
            bedrock=BedrockContext(region="us-east-1", operation="Converse",
                service_tier="default", performance="standard", additional_charges=False,
                sdk_retry_count=0, provider_latency_ms=80.0)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outbox", required=True, type=Path)
    parser.add_argument("--invoke", action="store_true", help="Make exactly two billable Bedrock calls")
    parser.add_argument("--model", help="Exact model or inference profile ID approved for your AWS account")
    parser.add_argument("--region", help="AWS source region")
    parser.add_argument("--stream", action="store_true", help="Stream the two billable calls")
    args = parser.parse_args()
    if args.invoke and (not args.model or not args.region):
        parser.error("--invoke requires --model and --region")
    if args.stream and not args.invoke:
        parser.error("--stream requires --invoke")
    outbox = Outbox(args.outbox)
    if not args.invoke:
        seed_fixture(outbox)
        print(json.dumps({"mode": "fixture", "pending": outbox.pending(), "model_calls": 0,
                          "note": "Synthetic counts and timings. Select Include synthetic test data in Workbench."}))
        return
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.Session(region_name=args.region).client("bedrock-runtime",
        config=Config(retries={"total_max_attempts": 1, "mode": "adaptive"},
                      connect_timeout=5, read_timeout=60))
    task_id = "bedrock-example-" + uuid.uuid4().hex
    prompts = [("classify", "Classify this fictional support request as billing or technical. "
                "Reply with one word: How can I download my invoice?"),
               ("draft", "Draft one sentence for a fictional help center: explain that a signed-in "
                "customer can download invoices from Billing. Do not claim to have performed any action.")]
    try:
        for stage, prompt in prompts:
            request = dict(task_id=task_id, project="bedrock-example", stage=stage,
                modelId=args.model, messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 64})
            if args.stream:
                with capture_converse_stream(client, outbox, **request) as stream:
                    for _ in stream:
                        pass
            else:
                capture_converse(client, outbox, **request)
    except (BotoCoreError, ClientError):
        parser.exit(1, "AWS call failed. Check credentials, region and model access. Metadata remains in the outbox.\n")
    print(json.dumps({"mode": "observed", "task_id": task_id, "pending": outbox.pending(),
                      "note": "Two calls completed. Run connector delivery to send metadata."}))


if __name__ == "__main__":
    main()
