# 100-company smoke test

Batch: `batches/smoke-100.jsonl`, produced from Builderr's public company universe with
`select_entry_batch.py --universe signalpost-universe.jsonl.gz --count 100`. Same file the
kit documents, so the sample is comparable with any other entry built on it.

## Command

```bash
uv run python scripts/run_agent.py \
  --organisations batches/smoke-100.jsonl \
  --bulk brreg-enheter.csv \
  --output out/envelopes.jsonl \
  --profiles-output out/profiles.jsonl \
  --report out/run-report.json \
  --run-id smoke5-final \
  --workers 10 \
  --budget-seconds 90
```

## Result

Machine: Linux, 20 cores, Python 3.12.3, `uv`-managed environment, residential connection.
Date: 2026-10-17.

| Measure | Value |
|---|---|
| Input organisation numbers | 100 |
| Envelopes emitted | 100 |
| Missing rows | 0 |
| Wall clock | 47.6 s |
| HTTP requests | 650 |
| Third-party cost | $0.00 |
| Latency p50 / p95 / max | 2,350 ms / 11,323 ms / 26,227 ms per company |
| Claims per company | 29.2 average |
| Evidence rows | 2,056 |

Validation from `out/run-report.json`: one envelope per input, unique organisation numbers,
no missing rows, every module in a terminal state.

## Coverage on this batch

| Fact family | Companies with a published value |
|---|---|
| Legal name | 100/100 |
| Annual result | 100/100 |
| Total assets | 100/100 |
| Equity | 100/100 |
| Operating result | 98/100 |
| Debt | 98/100 |
| Role holders | 100/100 |
| Revenue | 71/100 |
| Registered workplaces | 73/100 |
| Contact address from the registry row | 26/100 |
| Verified company site | 15/100 |
| Group subsidiaries | 8/100 |
| Phone number | 6/100 |
| Careers page, open roles | 4/100 |
| Wikidata record | 1/100 |

The site number deserves a note. Seven of these 100 companies had a homepage in the registry
field. The other eight were reached by turning the contact address the company filed with the
same registry row into a candidate host and letting the identity gate judge the page. Nine
candidates failed for real reasons: dead domains, certificate errors, timeouts. Those records
carry `source_error` and the reason, and no value from the site was published.

## Evidence hygiene

| Check | Share |
|---|---|
| Published claims carrying evidence ids | 100% |
| Published claims whose evidence resolves to a row in the same envelope | 100% |
| Evidence rows with a source URL | 100% |
| Evidence rows with a content hash | 100% |
| Evidence rows with a retrieval time | 100% |

## Claim states across the batch

| State | Claims |
|---|---|
| available | 2,652 |
| not_available | 253 |
| failed | 9 |
| not_applicable | 2 |

Nothing was counted as zero. A source that answered with an empty list produces
`not_available` with the reason in the claim note; a source that refused produces `blocked`; a
source that broke produces `failed`.

## Reproducing it

`docs/samples/` holds three envelopes taken from this run: the richest profile, a median one
and one that stopped at the registry. `docs/smoke-test-report.json` is the machine-readable
report the runner wrote. Everything else regenerates from the command above, and the only
network inputs are the public registry endpoints, the company sites of these 100 companies and
one batched Wikidata query.

---

*This document was developed with the assistance of generative AI tools for research, structuring, and content generation. Final content has been reviewed and validated by the author. Full compliance with: Reg. (EU) 2024/1689 (AI Act) Art. 50 · Italian Law 132/2025 Art. 13 · EU Code of Practice on AI Transparency (2026) · U.S. AI Labeling Act (S. 4915) · U.S. H.R.8479 · U.S. Executive Order on AI (Dec 2025) · California TFAIA & AB 2013 (eff. Jan 2026).*
