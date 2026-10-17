# signalpost-norway-agent

Give this agent a Norwegian organisation number and it returns one JSON envelope for that
company: legal identity, filed accounts, role holders, registered workplaces, group structure,
the verified company site and whatever the company publishes about its own activity. Every
value carries a source URL, a retrieval time and a content hash. A number the sources did not
give stays missing and says why.

No API key exists in this repository. No model is called. The whole 100-company smoke run cost
$0.00 and finished in 47.6 seconds.

## Run it

Python 3.12+ and `uv`.

```bash
git clone https://github.com/ChiaraDeVenuto/signalpost-norway-agent.git
cd signalpost-norway-agent
uv sync

curl -sSL 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv' -o brreg-enheter.csv

uv run python scripts/run_agent.py \
  --organisations batches/smoke-100.jsonl \
  --bulk brreg-enheter.csv \
  --output out/envelopes.jsonl \
  --profiles-output out/profiles.jsonl \
  --report out/run-report.json
```

That is the one evaluator command. It reads a JSONL, JSON or plain-text list of organisation
numbers (also `SIGNALPOST_BATCH=<file>` if you prefer the environment), and it writes one
terminal envelope per input, plus the report and a static profile viewer at
`out/profiles.html`.

Useful flags: `--workers N` (default 8), `--budget-seconds` (default 120 per company),
`--previous out/profiles.jsonl` (refresh diff), `--with-history` (annual report PDF index),
`--resume`, `--skip-wikidata`.

## What the output looks like

Each line of `out/envelopes.jsonl` follows the minimal output contract: `organisation_number`,
`run`, `claims`, `evidence`, `changes`, `errors`, `operations`. The agent also keeps the kit's
`state`, `modules` and `profile` blocks, so a reviewer can see which source answered and which
did not without opening the claims.

Claim availability uses only `available`, `not_available`, `blocked`, `not_applicable`,
`ambiguous` and `failed`. The difference between them matters:

- `available` means a source answered and the value is attached to a row in `evidence`.
- `not_available` means the source answered and returned nothing for this field. A checked
  careers page with no open roles is `not_available`, and that is a finding.
- `blocked` means the source refused us or its `robots.txt` forbids our user agent.
- `failed` means the request itself broke: DNS, certificate, timeout, rate limit.

Three full envelopes from the smoke run are in `docs/samples/`.

## How identity stays pinned to the number

Wrong-company facts are the failure mode that kills a research agent, so every path into a
profile is keyed on the organisation number:

1. The bulk registry snapshot is streamed once and the row for that exact number is taken. The
   row carries the snapshot SHA-256 and the row key.
2. Live registry, accounts, roles, group and subunit endpoints are called with the number in
   the URL. Nothing is searched by name.
3. Wikidata is queried with `wdt:P2333`, the Norwegian organisation number property. Every row
   that does not carry the requested number is discarded before it reaches a profile.
4. A website candidate comes from the registry row itself: the `hjemmeside` field, the contact
   address the company filed with the same row, or the Wikidata item from step 3. Hosts are
   never guessed from a company name.
5. Whatever the crawl returns still has to pass the identity gate before a single value is
   published. The gate wants a strong name match or the organisation number in the page, and it
   checks every internal page against the registrant domain. A weak match produces `blocked`
   with the score and the method in the note.

Subunits, parents and subsidiaries get the same treatment through the group and subunit
endpoints, so a franchisee never inherits a franchisor's facts.

## Where each fact comes from

| Family | Source | Class |
|---|---|---|
| Identity, addresses, industry, employees, status, incorporation | Brønnøysundregistrene bulk CSV and `enhetsregisteret` | official registry |
| Filed accounts: revenue, operating result, profit before tax, annual result, assets, equity, debt, reporting period | `regnskapsregisteret` | official filing |
| Annual report PDF copies | `regnskapsregisteret` (opt-in `--with-history`, 30 req/min) | official filing |
| Directors, CEO, chair, role change dates | `enhetsregisteret/roller` | official registry |
| Group parents and subsidiaries with ownership share and link date | `enhetsregisteret/konsernstruktur` | official registry |
| Registered workplaces (subunits) with address and headcount | `enhetsregisteret/underenheter` | official registry |
| Verified site, company description, careers and news links, dated news, contact details | the company's own site | company owned |
| Wikipedia articles, social handles, inception, coordinates | Wikidata via `P2333` | CC0 |

`docs/SOURCES.md` explains the rights position for each source, the robots and URL policy, and
what the agent refuses to collect. `docs/LIMITATIONS.md` lists what the sources cannot answer.

## Refresh

```bash
uv run python scripts/run_agent.py --organisations batch.jsonl --bulk brreg-enheter.csv \
  --previous out/profiles.jsonl --output out/refreshed.jsonl --profiles-output out/profiles.jsonl
```

Claim keys are compared with the previous snapshot and typed changes come back in `changes`:
`new_role`, `new_location`, `new_filing`, `new_job`, `new_activity`, `changed_financials`,
`new_claim`, `removed_or_now_unsupported`. Re-running on unchanged sources produces no changes
and rewrites the same values, which is what makes the replay idempotent. The bundled sample
data demonstrates it:

```bash
uv run python scripts/run_refresh_replay.py --manifest tests/fixtures/refresh-snapshots.json --output out/refresh-demo.json
```

## The viewer

`out/profiles.html` is one file with no dependencies and no network calls. Search by name,
organisation number, municipality or industry on desktop or on a phone. Each published value
shows its source, its class, its retrieval time and its reporting period, so an auditor can
check a claim without leaving the page.

## Cost, models, licences

- Third-party APIs with a price: none. `third_party_cost_usd` is 0 for every envelope and for
  the run report.
- Models: none at build time or at run time. The summary is a deterministic template over the
  published claims, which is why every sentence repeats the evidence ids it was built from.
- Code licences: this repository's own code ships under MIT (see `LICENSE`). The upstream
  starter kit has no licence file, so its files keep their original headers and provenance is
  declared below. Registry data from Brønnøysundregistrene is public register data; Wikidata is
  CC0; company-site text is used as evidence with a hash and a link, and the pages themselves
  are never republished.
- Dependencies are pinned in `uv.lock`. `uv sync` builds a working environment offline from
  that lock.

## Numbers from the 100-company smoke run

100 inputs, 100 envelopes, 0 missing rows, 650 requests, 47.6 s wall clock, 29.2 claims per
company, 2,056 evidence rows.

At ten times the batch, on 1,000 companies with eight workers: 1,000 envelopes, 0 missing rows,
6,353 requests, 485.2 s, same $0.00, and every envelope inside its per-company budget. Every published claim carries resolvable evidence; every evidence
row carries a URL, a content hash and a retrieval time. Fact families and their hit rates are
in `docs/SMOKE-TEST.md`, along with the machine-readable report and three sample envelopes.

## Layout

```
scripts/run_agent.py        the evaluator command: batch in, envelopes out
scripts/build_ui.py         static profile viewer
src/norway_company_agent/
  official.py               registry, accounts, roles, group, subunits
  website.py                robots-checked crawl and the identity gate
  wikidata.py               P2333 batched lookup, CC0
  footprint.py              careers, news, contact from the pages already fetched
  claims.py                 profile to claims plus evidence rows
  synthesis.py              deterministic summary and refresh diff
  batch.py, evidence.py, http.py, sampling.py, identity.py   kit modules
tests/                      113 tests, offline
batches/smoke-100.jsonl     the smoke batch
docs/                       sources, limits, smoke test, samples
```

## Provenance

The starting point is Builderr's public starter kit for this challenge
(`https://builderr.ai/signalpost-starter-kit.tar.gz`). Its crawl safety, evidence records,
identity gate, batch reader, sampling and the reference batch script are kept as they were, and
the 104 kit tests still pass. Added here: `wikidata.py`, `footprint.py`, `claims.py`,
`synthesis.py`, `run_agent.py`, `build_ui.py` and the tests for them. Modified: `website.py`
(link extraction on the fetched pages), `official.py` (e-mail, address line, municipality and
incorporation date kept from the live registry response). Everything else is upstream.

## Contact

Agent name: `signalpost-norway-agent`. Questions and submissions: `submit@builderr.ai` for
entries, `inquiries@builderr.ai` for everything else.

---

*This document was developed with the assistance of generative AI tools for research, structuring, and content generation. Final content has been reviewed and validated by the author. Full compliance with: Reg. (EU) 2024/1689 (AI Act) Art. 50 · Italian Law 132/2025 Art. 13 · EU Code of Practice on AI Transparency (2026) · U.S. AI Labeling Act (S. 4915) · U.S. H.R.8479 · U.S. Executive Order on AI (Dec 2025) · California TFAIA & AB 2013 (eff. Jan 2026).*
