# Fictional Bedrock billing export

This is authored teaching data, **not an AWS-issued report or invoice**.
Account `000000000000`, usage types, operation, model display hints, amounts,
tokens, and timings are fictional. No model calls were made to create it.

- `legacy-cur.csv`: five rows using Legacy CUR headers.
- `cur-2.0.csv`: the same rows using Workbench's projected CUR 2.0 CSV contract.
- `matching-usage.json`: two fictional Bedrock capture events for one task.
- `expected-totals.json`: independent authored controls and expected differences.
- `sample-check.json`: checks of the fictional workflow, not real-bill acceptance.

| Item | Fictional USD |
|---|---:|
| Input charge | 0.0000875 |
| Output charge | 0.0000600 |
| Unassigned usage | 0.004 |
| Fee | 0.010 |
| Credit | -0.002 |
| Imported total | 0.0121475 |
| Matching captured estimate | 0.0001295 |
| Linked charges minus captured estimate | 0.000018 |

The display hint deliberately does not identify a runtime model. The demo declares
its two-call scope explicitly. Fees, credits and unrelated usage stay unassigned.
CSV `workbench_evidence=fixture` markers prevent importing this as real billing.

In the authenticated app, open **Billing reconciliation → Load fictional billing
example**. This loads the same sample and its matching usage in the separate
fixture scope. Use **Download sample CSVs and usage** to obtain this bundle.
Manual real-bill import intentionally rejects these marked sample files.

To rebuild and verify the bundle from source:

```sh
uv run --locked python scripts/build_billing_sample.py
```

The script uses a temporary database, checks both formats, exact totals,
matching usage, and idempotent loading, then removes the database. It does not
touch your seeded or clean deployments. The ZIP is written to
`artifacts/bedrock-billing-sample.zip`.
