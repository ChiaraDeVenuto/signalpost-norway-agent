# Limits of this agent

Everything below is a known boundary. Each one has a consequence you can check in the output.

## Most Norwegian companies publish almost nothing about themselves

In the 100-company smoke batch, 7 companies had a homepage in the registry field, and 26 had a
contact address the company filed itself. That second number is the reason the agent turns a
registry e-mail address into a website candidate and then runs the identity gate on whatever
comes back. It lifts published sites to 10 companies in 100, with 5 more candidates reported as
`ambiguous` instead of being asserted. The remaining companies have no site we are allowed to
trust, so their profiles stop at the registry, the accounts and the role register. That is the
real ceiling for private `AS` companies, and it is the same ceiling for every agent in this
challenge.

## A contact e-mail domain is a lead, not proof

Turning the address the company filed into a host recovers sites the registry never listed. It
also produces hosts that belong to an agency, a web shop or a brand the register does not
mention, so the agent separates three outcomes. A page that carries the legal name or the
organisation number is published with the gate score attached. A page with no name evidence at
all is reported with availability `ambiguous`, the score and the method, and nothing from that
page enters the profile. A parked or for-sale page produces `not_available` with the reason. In
the smoke batch this split 15 fetched candidates into 10 published sites and 5 ambiguous ones.
Coverage loses a little, and every asserted claim keeps its support.

## Wikidata coverage is thin for private companies

`P2333` (Norwegian organisation number) is exact, which is why it is used, and rare, which is
why it only helps on large companies. One company out of 100 in the smoke batch had a Wikidata
item. Wikipedia articles, coordinates, inception dates and social handles therefore appear on
almost no profile in a random sample, and they will appear on a few of the large ones in the
official 1,000.

## The prose is assembled, not written

There is no model in this repository. Sentences come from a template over published claims, so a
summary reads like a filing note. You get "Filed accounts for 2025 show revenue NOK 1,240,000,
annual result NOK -85,000." Ambition, tone and market positioning stay outside the profile.
Every sentence
carries the evidence ids it was built from, which is the trade we took: auditable sentences over
fluent ones.

## Annual report PDFs are optional and rate limited

`--with-history` fetches the index of filed PDF copies from Regnskapsregisteret, which answers
at 30 requests per minute. That flag is off by default because a 1,000-company run would spend
over half an hour on it, and a run that runs out of time scores zero for every company it never
reached. With the flag off, the agent publishes figures from the accounts endpoint and simply
does not publish PDF links.

## A dead domain stays dead

A company that filed `example.no` in 2009 and never renewed the domain produces
`source_error` with the reason: DNS failure, certificate failure, connection reset or timeout.
The agent does not substitute a similar-looking company and does not retry forever. Two
companies in the smoke batch had domains that no longer resolve; both records say so.

## Dated news only exists where the company dates it

A news item is published only when the company's own page shows a date next to a title. Pages
that load items with JavaScript, or that show a list without dates, produce `news_page:
not_available` with the page URL rather than an invented timeline.

## Social accounts are never scraped

A handle is published when Wikidata carries it or when a link appears on the verified company
site. The LinkedIn, Facebook, Instagram, X and TikTok pages behind those links are never
requested. That keeps the agent inside the platform terms and means a company whose only
presence is a Facebook page shows an empty footprint.

## A first run reports no changes

`changes` is computed against a previous snapshot supplied with `--previous`. On a first run
every claim is new, so the list stays empty on purpose. Refresh replay on the bundled sample
data (`scripts/run_refresh_replay.py`) shows the change machinery working end to end.

## The per-company budget is real

`--budget-seconds` (default 120) is a wall clock, not a suggestion. When a company burns its
budget on a slow source, the remaining modules are skipped and the envelope says which ones and
why. The runner still emits the envelope, because a missing row is the one outcome that cannot
be scored.

---

*This document was developed with the assistance of generative AI tools for research, structuring, and content generation. Final content has been reviewed and validated by the author. Full compliance with: Reg. (EU) 2024/1689 (AI Act) Art. 50 · Italian Law 132/2025 Art. 13 · EU Code of Practice on AI Transparency (2026) · U.S. AI Labeling Act (S. 4915) · U.S. H.R.8479 · U.S. Executive Order on AI (Dec 2025) · California TFAIA & AB 2013 (eff. Jan 2026).*
