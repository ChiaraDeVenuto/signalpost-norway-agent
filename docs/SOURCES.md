# Sources, rights and URL policy

This agent reads four sources and nothing else. Each one is listed here with the reason it is
allowed, what we publish from it, and the limits we impose on ourselves.

## 1. Brønnøysundregistrene, Enhetsregisteret

- Endpoints: bulk CSV (`https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv`),
  per-entity JSON (`https://data.brreg.no/enhetsregisteret/api/enheter/{org}`), roles
  (`.../roller`), group structure (`.../konsernstruktur/{org}`), subunits
  (`.../underenheter?overordnetEnhet={org}`).
- Why it is allowed: Brønnøysundregistrene publishes the register and its API for open reuse.
  This is the official register of Norwegian businesses, and the organisation number we are
  given comes from it.
- What we publish from it: legal name, organisation number, legal form, business address,
  postal address when it differs, municipality, industry code, registered employee count,
  incorporation date, date of registration in the register, date the articles were adopted,
  registered purpose and registered activity, institutional sector, language form, share capital
  with currency and share count, VAT registration flag, parent organisation number, contact
  e-mail, telephone and mobile numbers, the homepage field, the most recent submitted accounts,
  role holders, group links, registered workplaces. Every value is carried from the column it
  sits in, and the evidence span names that column, so a reviewer can put the span and the
  snapshot side by side.
- Limits we impose: one bulk read per run (streamed once, not per company), then at most five
  per-company JSON calls. We do not hammer the register and we keep a per-company time budget.

## 2. Regnskapsregisteret (annual accounts)

- Endpoints: `https://data.brreg.no/regnskapsregisteret/regnskap/{org}` for the figures and
  `.../regnskap/aarsregnskap/kopi/{org}/aar` for the index of filed PDF copies.
- Why it is allowed: same public register, official filings submitted by the companies
  themselves.
- What we publish from it: revenue, operating result, profit before tax, annual result, assets,
  equity, debt, each with the reporting period taken from the filing record. Figures are carried
  through as filed. Nothing is recomputed and no missing figure is turned into a zero.
- Limits we impose: the figures endpoint runs by default. The PDF index is behind a 30 requests
  per minute limit, so it only runs when the operator passes `--with-history`. Without that flag
  the PDF links are simply absent rather than invented.

## 3. Company-owned websites

- Discovery: the `hjemmeside` field in the registry row, the contact address the company filed
  with the same registry row, or the Wikidata item keyed on the organisation number. A host is
  never guessed from a company name alone.
- Why it is allowed: a company publishing its own site, careers page or news list is publishing
  it for the public. We also honour the kit's rule that only company-owned pages can support
  claims about what the company does and offers.
- What we publish from it: the verified URL, the company's own description of its work,
  registered contact addresses, career and news page links, dated news items, open roles listed
  on the careers page. Sentiment, ratings and third-party opinions are never published from
  marketing copy.
- Limits we impose:
  - `robots.txt` is fetched and obeyed for every host, for our user agent, before any page read.
  - Only `http` and `https` URLs, never a local or private address, and the address is resolved
    and re-checked after every redirect.
  - Same registrant domain for the homepage and the priority pages. A redirect to another
    registrant closes the crawl.
  - Byte caps: 4 MB for the homepage, 1.2 MB for each extra page, redirect cap 5.
  - At most four internal priority pages and three extra pages (careers, news, contact) per
    company, 8 to 15 second timeouts.
  - Identity before any page value. The gate matches the legal name or the organisation number
    on the page, and the score it returns travels with the claim. The URL itself is published
    when the registry lists it as the homepage, and when it was reached through the contact
    e-mail domain with at least part of the legal name present on the page or in the host. A URL
    reached through the contact e-mail domain with no name evidence at all is reported as
    `ambiguous` instead of being asserted, and no description or subpage from that page is
    published. A parked or for-sale page produces `not_available` with the reason.

## 4. Wikidata

- Endpoint: `https://query.wikidata.org/sparql`, property `P2333` (Norwegian organisation
  number).
- Why it is allowed: Wikidata releases its content under CC0, and we query it by the identifier
  we already trust rather than by name.
- What we publish from it: official website statements, social account handles, Wikipedia
  articles, inception date, coordinates, organisation-level employee count, industry and legal
  form labels.
- Limits we impose: one batched query per 200 organisation numbers, three attempts with backoff
  on `429`, descriptive user agent. Every row that does not carry the requested organisation
  number is discarded before anything reaches the profile.

## Sources we deliberately do not use

- **LinkedIn, Meta platforms, Indeed, X**: automated collection against their terms. Handles may
  be published when they come from Wikidata or from a link on the company's own site; the pages
  themselves are never fetched.
- **Proff.no, Gule Sider, 1881.no and other directories**: they republish registry data we
  already hold, and `proff.no` and `gulesider.no` answer our requests with a block anyway. We do
  not route around those blocks.
- **Search engines and paid APIs**: none. No API key exists anywhere in this repository.

## Publishing rules

Every published value carries a source URL, a retrieval time and a content hash, plus a span or
selector pointing at the exact part of the response. A checked source that returns nothing
produces `not_available`, a source that refuses us produces `blocked`, a source that errors
produces `failed`. Those three states are different on purpose and none of them is rewritten to
zero.

## Contact

Questions about the sources or the crawl policy: `inquiries@builderr.ai`.

---

*This document was developed with the assistance of generative AI tools for research, structuring, and content generation. Final content has been reviewed and validated by the author. Full compliance with: Reg. (EU) 2024/1689 (AI Act) Art. 50 · Italian Law 132/2025 Art. 13 · EU Code of Practice on AI Transparency (2026) · U.S. AI Labeling Act (S. 4915) · U.S. H.R.8479 · U.S. Executive Order on AI (Dec 2025) · California TFAIA & AB 2013 (eff. Jan 2026).*
