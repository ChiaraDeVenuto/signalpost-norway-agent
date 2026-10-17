"""Exact-entity enrichment from Wikidata keyed on the Norwegian organisation number.

Wikidata property P2333 ("Norwegian organisation number") is the only external lookup used
here, because it keys on the identifier we already trust from Brreg. Nothing in this module
resolves an entity from a name. A row that does not carry the requested organisation number
never enters the result.

Licence: Wikidata content is CC0.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .evidence import evidence
from .http import FetchResult

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "signalpost-norway-agent/1.0 (company research; no personal data retained)"
CHUNK_SIZE = 200

PROPERTY_MAP = {
    "official_website": "P856",
    "facebook": "P2013",
    "instagram": "P2003",
    "x": "P2002",
    "youtube": "P2397",
    "linkedin": "P4264",
    "wikimedia Commons": "P373",
    "coordinates": "P625",
    "inception": "P571",
    "employees": "P1128",
    "industry": "P452",
    "legal_form": "P1454",
}

SOCIAL_PLATFORMS = ("facebook", "instagram", "x", "youtube", "linkedin")


def build_query(organisation_numbers: list[str]) -> str:
    values = " ".join('"%s"' % org for org in organisation_numbers)
    optionals = "\n".join(
        "  OPTIONAL { ?item wdt:%s ?%s. }" % (prop, key.replace(" ", "_"))
        for key, prop in PROPERTY_MAP.items()
    )
    projected = " ".join("?%s" % key.replace(" ", "_") for key in PROPERTY_MAP)
    return """
SELECT ?item ?itemLabel ?itemDescription ?org ?industryLabel ?legalFormLabel %(projected)s ?nbArticle ?enArticle ?nnArticle WHERE {
  VALUES ?org { %(values)s }
  ?item wdt:P2333 ?org .
%(optionals)s
  OPTIONAL { ?nbArticle schema:about ?item. ?nbArticle schema:isPartOf <https://no.wikipedia.org/>. }
  OPTIONAL { ?enArticle schema:about ?item. ?enArticle schema:isPartOf <https://en.wikipedia.org/>. }
  OPTIONAL { ?nnArticle schema:about ?item. ?nnArticle schema:isPartOf <https://nn.wikipedia.org/>. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "no,en". }
}""" % {"values": values, "optionals": optionals, "projected": projected}


def fetch_sparql(query: str, timeout: float = 45.0, attempts: int = 3) -> FetchResult:
    url = SPARQL_ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    last_error = "request failed"
    last_status = 0
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(8_000_000)
                body = json.loads(raw.decode("utf-8"))
            return FetchResult(
                url=url,
                status=200,
                elapsed_ms=0,
                bytes_received=len(raw),
                body=body,
                content_sha256=hashlib.sha256(raw).hexdigest(),
            )
        except urllib.error.HTTPError as exc:
            last_error = "HTTP %s" % exc.code
            last_status = exc.code
        except Exception as exc:  # network, decode, timeout
            last_error = "%s: %s" % (type(exc).__name__, str(exc)[:160])
            last_status = 0
        if attempt < attempts - 1:
            time.sleep(5.0 * (attempt + 1))
    return FetchResult(url=url, status=last_status, elapsed_ms=0, bytes_received=0, error=last_error)


def _bind(row: dict[str, Any], key: str) -> Any:
    cell = row.get(key)
    return cell.get("value") if cell else None


def _aggregate(rows: list[dict[str, Any]], organisation_number: str) -> dict[str, Any] | None:
    matched = [row for row in rows if _bind(row, "org") == organisation_number]
    if not matched:
        return None
    first = matched[0]
    record: dict[str, Any] = {
        "organisation_number": organisation_number,
        "item": _bind(first, "item"),
        "label": _bind(first, "itemLabel"),
        "description": _bind(first, "itemDescription"),
        "official_websites": [],
        "social": {},
        "articles": {},
        "coordinates": _bind(first, "coordinates"),
        "inception": _bind(first, "inception"),
        "employees": _bind(first, "employees"),
        "industry": _bind(first, "industryLabel"),
        "legal_form": _bind(first, "legalFormLabel"),
        "occurrences": len(matched),
    }
    for row in matched:
        website = _bind(row, "official_website")
        if website and website not in record["official_websites"]:
            record["official_websites"].append(website)
        for platform in SOCIAL_PLATFORMS:
            handle = _bind(row, platform)
            if handle:
                record["social"].setdefault(platform, [])
                if handle not in record["social"][platform]:
                    record["social"][platform].append(handle)
    for language in ("nb", "en", "nn"):
        article = _bind(first, "%sArticle" % language)
        if article:
            record["articles"][language] = article
    record["official_websites"] = rank_websites(record["official_websites"], record.get("label"))
    return record


def social_url(platform: str, handle: str) -> str | None:
    handle = str(handle or "").strip().lstrip("@")
    if not handle:
        return None
    templates = {
        "facebook": "https://www.facebook.com/%s",
        "instagram": "https://www.instagram.com/%s",
        "x": "https://x.com/%s",
        "youtube": "https://www.youtube.com/%s",
        "linkedin": "https://www.linkedin.com/company/%s",
    }
    template = templates.get(platform)
    return template % urllib.parse.quote(handle) if template else None


def rank_websites(candidates: list[str], name: str | None = None) -> list[str]:
    """Order candidate hosts so the corporate root comes before country branches.

    A Wikidata item for a large group can carry a dozen official website statements. Seeding a
    crawl from the wrong one would still be the right company, just the wrong landing page, so
    the ranking prefers an apex domain with an empty path, a global TLD and a host that echoes
    the legal name.
    """
    slug = "".join(ch for ch in str(name or "").casefold() if ch.isalnum())

    def score(url: str) -> tuple:
        parts = urllib.parse.urlparse(url)
        host = (parts.hostname or "").casefold()
        labels = [part for part in host.split(".") if part]
        path_segments = [part for part in (parts.path or "").split("/") if part]
        tld = labels[-1] if labels else ""
        global_tld = tld in {"no", "com", "org", "net", "com.br"}
        name_match = bool(slug) and any(token in host.replace(".", "") for token in (slug[:8], slug)) and len(slug) > 4
        return (
            0 if name_match else 1,
            0 if global_tld else 1,
            0 if not path_segments else 1,
            len(path_segments),
            len(host),
            url,
        )

    seen: set[str] = set()
    ordered = []
    for url in sorted(candidates, key=score):
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def lookup_organisations(
    organisation_numbers: list[str],
    fetcher=fetch_sparql,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return per-organisation records plus one evidence entry describing the query itself."""
    results: dict[str, dict[str, Any]] = {}
    queries = 0
    rows: list[dict[str, Any]] = []
    request_errors: list[str] = []
    for start in range(0, len(organisation_numbers), CHUNK_SIZE):
        chunk = organisation_numbers[start : start + CHUNK_SIZE]
        result = fetcher(build_query(chunk))
        queries += 1
        if result.status != 200:
            request_errors.append(result.error or "status %s" % result.status)
            continue
        batch = (result.body or {}).get("results", {}).get("bindings", [])
        rows.extend(batch)
        for org in chunk:
            record = _aggregate(batch, org)
            if record:
                results[org] = record
    content_sha256 = hashlib.sha256(
        json.dumps(sorted(results), sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    query_evidence = evidence(
        "wikidata",
        "available" if results else ("source_error" if request_errors else "not_found"),
        "wikidata_cc0_sparql",
        SPARQL_ENDPOINT,
        value={
            "keyed_on": "P2333 Norwegian organisation number",
            "requested": len(organisation_numbers),
            "matched": len(results),
            "queries": queries,
            "errors": request_errors[:5],
            "records": results,
        },
        note="Exact-entity lookup. Rows without the requested organisation number are discarded.",
        content_sha256=content_sha256,
    )
    return results, [query_evidence], {"queries": queries, "matched": len(results), "errors": len(request_errors)}
