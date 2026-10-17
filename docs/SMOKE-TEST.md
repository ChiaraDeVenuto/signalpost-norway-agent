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
  --run-id smoke-final \
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
| Wall clock | 47.5 s |
| HTTP requests | 650 |
| Third-party cost | $0.00 |
| Latency p50 / p95 / max | 2,300 ms / 11,602 ms / 26,263 ms per company |
| Claims per company | 36.9 average |
| Evidence rows | 2,830 |

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
| VAT registration flag | 100/100 |
| Date of registration in the register | 100/100 |
| Language form | 100/100 |
| Registered purpose | 99/100 |
| Date the articles were adopted | 99/100 |
| Institutional sector | 98/100 |
| Share capital | 93/100 |
| Revenue | 71/100 |
| Registered workplaces | 73/100 |
| Registered activity | 61/100 |
| Telephone or mobile number | 31/100 |
| Contact address from the registry row | 26/100 |
| Postal address | 25/100 |
| Company site | 10/100 |
| Group subsidiaries | 8/100 |
| Careers page, open roles | 4/100 |
| Wikidata record | 0/100 |

The site line needs the full story. Seven of these 100 companies carry a homepage in the
registry field, and that value is published straight from the field; four of the seven were
also crawled and matched. Three more companies got a published site from the contact address
they filed with the same registry row, and in each of those three the identity gate found the
legal name on the page. Five further candidates came back with no legal-name or
organisation-number evidence anywhere on the page or in the host; they are reported as
`ambiguous` with the score, and no description or subpage from those pages entered the
profiles. Nine candidates failed for real reasons: dead domains, certificate errors, timeouts.
Those records carry `source_error` with the reason and no value.

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
| available | 3,420 |
| not_available | 254 |
| ambiguous | 5 |
| failed | 9 |
| not_applicable | 2 |

Nothing was counted as zero. A source that answered with an empty list produces
`not_available` with the reason in the claim note; a source that refused produces `blocked`; a
source that broke produces `failed`; a candidate URL the identity evidence does not support
produces `ambiguous`.

## Reproducing it

`docs/samples/` holds three envelopes taken from this run: the richest profile, a median one
and one that stopped at the registry. `docs/smoke-test-report.json` is the machine-readable
report the runner wrote. Everything else regenerates from the command above, and the only
network inputs are the public registry endpoints, the company sites of these 100 companies and
one batched Wikidata query.

## 1,000-company scale run

Same code, same flags, ten times the batch. `batches/scale-1000.jsonl`, run 2026-10-17, ten
workers to keep the load on Brønnøysundregistrene polite.

| Measure | Value |
|---|---|
| Input organisation numbers | 1,000 |
| Envelopes emitted | 1,000 |
| Missing rows | 0 |
| Wall clock | 393.6 s |
| HTTP requests | 6,341 |
| Third-party cost | $0.00 |
| Latency p50 / p95 / max | 2,456 ms / 11,896 ms / 36,239 ms per company |
| Claims | 37.2 per company, 37,163 in total |
| Evidence rows | 28,631 |

| Fact family | Companies with a published value |
|---|---|
| Legal name | 994/1,000 |
| Annual result, total assets | 997/1,000 |
| Equity | 995/1,000 |
| Role holders | 994/1,000 |
| Debt | 989/1,000 |
| Operating result | 960/1,000 |
| VAT registration flag | 994/1,000 |
| Date of registration in the register | 994/1,000 |
| Language form | 994/1,000 |
| Institutional sector | 981/1,000 |
| Date the articles were adopted | 961/1,000 |
| Registered purpose | 960/1,000 |
| Share capital | 932/1,000 |
| Revenue | 735/1,000 |
| Registered workplaces | 742/1,000 |
| Registered activity | 647/1,000 |
| Telephone or mobile number | 319/1,000 |
| Contact address from the registry row | 247/1,000 |
| Postal address | 242/1,000 |
| Company description from the site | 101/1,000 |
| Company site | 122/1,000 |
| Group subsidiaries | 69/1,000 |
| Careers page, open roles | 25/1,000 |
| Wikidata record | 1/1,000 |

Of the 122 published sites, 106 come from the homepage the company filed in the registry row
and 16 from a contact-e-mail candidate that passed the identity gate. Thirty-nine further
candidates came back with no legal-name or organisation-number evidence and are reported as
`ambiguous` with the score instead of being asserted. The revenue line is the filed number:
265 of these companies submitted accounts with no revenue figure in them, and the agent does
not invent one.

Claim states across the batch: 34,449 `available`, 2,562 `not_available`, 60 `failed`,
39 `ambiguous`, 46 `not_applicable`, 7 `blocked`. Module states: 5,298 `complete`, 2,734
`not_found`, 60 `source_error`, 46 `not_applicable`, 5 refused by `robots.txt`, 2 blocked by a
host policy. The six companies without a legal name are numbers the register itself does not
answer, and their envelopes say so instead of inventing a name.

Every available claim carries a resolvable evidence id: 34,449 of 34,449. Every evidence row
carries a source URL and a retrieval time; 28,629 of 28,631 carry a content hash, the two
exceptions being accounts responses that came back empty and therefore had no body to hash.

At this scale the run stays inside the per-company budget for every company: no envelope
reports an exhausted budget, and the slowest single company took 36.2 s.

---

*This document was developed with the assistance of generative AI tools for research, structuring, and content generation. Final content has been reviewed and validated by the author. Full compliance with: Reg. (EU) 2024/1689 (AI Act) Art. 50 · Italian Law 132/2025 Art. 13 · EU Code of Practice on AI Transparency (2026) · U.S. AI Labeling Act (S. 4915) · U.S. H.R.8479 · U.S. Executive Order on AI (Dec 2025) · California TFAIA & AB 2013 (eff. Jan 2026).*
