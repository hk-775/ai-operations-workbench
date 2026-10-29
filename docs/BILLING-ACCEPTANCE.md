# Real billing acceptance

Use a private complete export and matching captured Bedrock usage. The authored
test files and fictional example cannot establish customer acceptance.

1. Import every CSV part from one export generation into an isolated customer
   test workspace. Declare the exact account/model/region/mode/source scope.
2. Download the reconciliation JSON from Billing reconciliation. Keep it beside
   the original CSV files, outside Git.
3. Have the billing owner independently calculate the normalized row count,
   total positive charges, total negative adjustments, and net charges, using
   net unblended cost where present and otherwise unblended cost. Obtain captured
   call count and saved estimates from the application's independent run record.
   Do not copy Workbench's answers into the controls.
4. Create a private configuration and run the check below.
5. Review unmatched charges, provenance, incomplete capture, immutable revisions,
   and exact replay behavior. Export completeness and ownership remain reviewer
   attestations; a hash or supplied invoice ID does not authenticate a bill.

Configuration shape (replace every illustrative value with the reviewed scope):

```json
{
  "upload": {
    "format": "legacy-cur",
    "account_id": "123456789012",
    "month": "2026-10",
    "currency": "USD",
    "name": "Private acceptance",
    "files": ["part-1.csv", "part-2.csv"],
    "complete_snapshot": true
  },
  "reconciliation_file": "reconciliation.json",
  "controls": {
    "imported_charges": "12",
    "positive_charges": "14",
    "negative_adjustments": "-2",
    "row_count": 10,
    "captured_calls": 20,
    "comparable_estimate_usd": "9",
    "reviewer": "Billing owner"
  }
}
```

Paths are relative to the configuration file. Amounts above are placeholders.

```sh
uv sync --locked
uv run --locked python -m workbench.billing_acceptance \
  --config .pilot/acceptance/config.json \
  --output .pilot/acceptance/receipt.json
```

The command is read-only. It checks the exact snapshot, scope, independent
controls, comparison arithmetic, and preservation of unassigned charges.
Missing/incomplete matching usage fails rather than producing a pass.
Receipts are owner-only and contain hashes/counts rather than account IDs or
monetary amounts. They still belong in private evidence storage.

For the requested [fictional billing sample](../data/billing-sample/README.md),
`scripts/build_billing_sample.py` verifies both CSV formats, exact controls,
matching usage, and replay in a temporary database. The acceptance command also
has an explicit `--fixture` mode, whose receipt says `fixture_checks_passed`.
It cannot be used as a real-data acceptance receipt.

During development on 2026-10-28, the configured AWS account returned no legacy
CUR definitions or Data Exports. No representative customer export was supplied.
**Real-data acceptance remains pending.** Automated tests exercise the acceptance
checker using explicitly authored data and do not change that status.

On October 29, a private versioned Legacy CUR export was provisioned in the
selected account and two real Nova Micro calls were captured independently.
Export creation and captured usage do not establish a billing pass: the first
actual report, complete scope, and independently reviewed controls are still required.
See [the account-owned operations guide](ACCEPTANCE-OPERATIONS.md).
