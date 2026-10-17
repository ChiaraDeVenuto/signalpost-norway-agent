"""External footprint observations for a single company.

Two inputs only: the identity-gated company site record produced by ``website.py``, and the
organisation-number keyed record produced by ``wikidata.py``. Neither input is resolved from
a name, so a parent, a franchise or a namesake cannot leak in through this path.

Everything here is a candidate until it carries a source URL, retrieval time and content hash.
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

from .evidence import evidence
from .website import SAFE_OPENER, USER_AGENT, _robots_allowed, assert_public_url, normalize_homepage

CAREER_TERMS = ("karriere", "career", "jobb", "job", "stillinger", "ledige-stillinger", "ledige", "work-with-us", "jobbmuligheter", "bli-en-av-oss")
NEWS_TERMS = ("nyheter", "news", "aktuelt", "press", "aktuelt-og-nytt", "aktuelt/nyheter", "presserom", "media", "siste-nytt", "artikler")
CONTACT_TERMS = ("kontakt", "contact")
MAX_EXTRA_PAGES = 2
PAGE_TIMEOUT = 8.0
MAX_BYTES = 1_200_000

DATE_PATTERNS = (
    re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{2})[./](\d{2})[./](20\d{2})\b"),
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+47)?\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{2}(?!\d)")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _matches(url: str, anchor: str, terms: tuple[str, ...]) -> bool:
    haystack = (urllib.parse.urlparse(url).path + " " + str(anchor or "")).casefold()
    return any(term in haystack for term in terms)


def pick_candidate(links: list[dict[str, str]], terms: tuple[str, ...]) -> str | None:
    for link in links:
        if _matches(link.get("url", ""), link.get("anchor", ""), terms):
            return link.get("url")
    return None


def fetch_page(url: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Fetch one additional company-owned page with robots, byte and redirect checks."""
    metrics = {"requests": 0, "bytes": 0, "latencies_ms": []}
    try:
        assert_public_url(url)
    except ValueError as exc:
        return None, {**metrics, "error": str(exc)}
    if not _robots_allowed(url, PAGE_TIMEOUT):
        return None, {**metrics, "requests": 1, "error": "robots.txt disallows this user agent"}
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with SAFE_OPENER.open(request, timeout=PAGE_TIMEOUT) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read(MAX_BYTES + 1)
            elapsed = int((time.monotonic() - started) * 1000)
            final_url = response.geturl()
        metrics.update({"requests": 2, "bytes": len(raw), "latencies_ms": [elapsed]})
        if len(raw) > MAX_BYTES or "html" not in content_type.lower():
            return None, {**metrics, "error": "unsupported or oversized page"}
        return {"url": final_url, "html": raw.decode("utf-8", errors="replace"), "sha256": _sha(raw)}, metrics
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return None, {**metrics, "requests": 2, "latencies_ms": [elapsed], "error": "%s: %s" % (type(exc).__name__, str(exc)[:140])}


def _date_lines(text: str, limit: int = 12) -> list[dict[str, str]]:
    """Find dated lines such as '2026-09-04 Kontrakt signert ...' on a company news page."""
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 15 or len(line) > 220:
            continue
        iso = DATE_PATTERNS[0].search(line)
        dotted = DATE_PATTERNS[1].search(line)
        if iso:
            date = "%s-%s-%s" % (iso.group(1), iso.group(2), iso.group(3))
        elif dotted:
            date = "%s-%s-%s" % (dotted.group(3), dotted.group(2), dotted.group(1))
        else:
            continue
        title = line.replace(iso.group(0) if iso else dotted.group(0), "").strip(" -|·•\t")
        title = re.sub(r"\s{2,}", " ", title)
        if len(title) < 8 or title in seen:
            continue
        seen.add(title)
        found.append({"title": title[:180], "date": date})
        if len(found) >= limit:
            break
    return found


def _job_titles(text: str, limit: int = 12) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = re.sub(r"\s{2,}", " ", raw_line.strip())
        if not (6 <= len(line) <= 90):
            continue
        lowered = line.casefold()
        signals = ("utvikler", "developer", "ingeniør", "engineer", "selger", "sales", "konsulent",
                   "consultant", "leder", "manager", "kokk", "sykepleier", "lærer", "analyst",
                   "controller", "ekspeditør", "mountain", "drift", "prosjektleder", "architect",
                   "designer", "accountant", "økonom", "produkt", "marked", "hr ", "miljøarbeider")
        if any(signal in lowered for signal in signals) and line not in seen:
            seen.add(line)
            titles.append(line)
        if len(titles) >= limit:
            break
    return titles


def extract_description(value: dict[str, Any]) -> dict[str, Any] | None:
    for node in value.get("structured_organisations") or []:
        text = node.get("description")
        if isinstance(text, str) and len(text.strip()) >= 25:
            return {"text": text.strip()[:600], "source": "json-ld"}
    meta = str(value.get("description") or "").strip()
    if len(meta) >= 25:
        return {"text": meta[:600], "source": "meta-description"}
    excerpt = str(value.get("main_text_excerpt") or "").strip()
    if len(excerpt) >= 60:
        return {"text": re.sub(r"\s{2,}", " ", excerpt)[:400], "source": "homepage-text"}
    return None


def build_footprint(
    profile: dict[str, Any],
    wikidata_record: dict[str, Any] | None,
    fetcher: Callable[[str], tuple[dict[str, Any] | None, dict[str, Any]]] = fetch_page,
) -> tuple[dict[str, Any], dict[str, Any]]:
    website = profile.get("evidence", {}).get("website") or {}
    value = website.get("value") or {}
    site_ok = website.get("status") == "available" and value.get("identity_assessment", {}).get("publishable")
    links = list(value.get("internal_links") or [])
    pages = value.get("pages") or []
    for page in pages:
        for link in page.get("internal_links") or []:
            if link not in links:
                links.append(link)

    payload: dict[str, Any] = {
        "verified_website": value.get("final_url") if site_ok else None,
        "company_description": extract_description(value) if site_ok else None,
        "social_handles": [],
        "wikipedia": {},
        "careers": {"state": "not_checked", "page_url": None, "openings": []},
        "news": {"state": "not_checked", "page_url": None, "items": []},
        "contact": {"state": "not_checked", "emails": [], "phones": [], "page_url": None},
        "sources": [],
    }

    if site_ok:
        for handle in value.get("social_links") or []:
            payload["social_handles"].append({**handle, "source": "company_site", "rights_status": "approved"})
    if wikidata_record:
        for platform, handles in (wikidata_record.get("social") or {}).items():
            for handle in handles[:1]:
                payload["social_handles"].append(
                    {"platform": platform, "handle": handle, "source": "wikidata_cc0", "rights_status": "approved"}
                )
        for language, url in (wikidata_record.get("articles") or {}).items():
            payload["wikipedia"][language] = url

    metrics = {"requests": 0, "bytes": 0, "latencies_ms": [], "errors": []}
    career_page = pick_candidate(links, CAREER_TERMS)
    news_page = pick_candidate(links, NEWS_TERMS)
    contact_page = pick_candidate(links, CONTACT_TERMS)

    extra = 0
    if career_page and extra < MAX_EXTRA_PAGES:
        extra += 1
        page, page_metrics = fetcher(career_page)
        metrics["requests"] += page_metrics.get("requests", 0)
        metrics["bytes"] += page_metrics.get("bytes", 0)
        metrics["latencies_ms"].extend(page_metrics.get("latencies_ms") or [])
        if page:
            openings = _job_titles(_page_text(page["html"]))
            payload["careers"] = {
                "state": "available" if openings else "not_available",
                "page_url": page["url"],
                "openings": openings,
                "retrieved_at": _now(),
                "content_sha256": page["sha256"],
            }
        else:
            payload["careers"] = {"state": "blocked" if "robots" in str(page_metrics.get("error", "")) else "not_available", "page_url": career_page, "openings": []}
            metrics["errors"].append({"url": career_page, "error": page_metrics.get("error")})

    if news_page and extra < MAX_EXTRA_PAGES:
        extra += 1
        page, page_metrics = fetcher(news_page)
        metrics["requests"] += page_metrics.get("requests", 0)
        metrics["bytes"] += page_metrics.get("bytes", 0)
        metrics["latencies_ms"].extend(page_metrics.get("latencies_ms") or [])
        if page:
            items = _date_lines(_page_text(page["html"]))
            payload["news"] = {
                "state": "available" if items else "not_available",
                "page_url": page["url"],
                "items": items,
                "retrieved_at": _now(),
                "content_sha256": page["sha256"],
            }
        else:
            payload["news"] = {"state": "blocked" if "robots" in str(page_metrics.get("error", "")) else "not_available", "page_url": news_page, "items": []}
            metrics["errors"].append({"url": news_page, "error": page_metrics.get("error")})

    if contact_page:
        page, page_metrics = fetcher(contact_page)
        metrics["requests"] += page_metrics.get("requests", 0)
        metrics["bytes"] += page_metrics.get("bytes", 0)
        metrics["latencies_ms"].extend(page_metrics.get("latencies_ms") or [])
        text = _page_text(page["html"]) if page else ""
        payload["contact"] = {
            "state": "available" if text else ("blocked" if "robots" in str(page_metrics.get("error", "")) else "not_available"),
            "page_url": contact_page,
            "emails": sorted({m for m in EMAIL_RE.findall(text)})[:5],
            "phones": sorted({re.sub(r"\s+", "", p) for p in PHONE_RE.findall(text)})[:5],
            "content_sha256": page["sha256"] if page else None,
            "retrieved_at": _now() if page else None,
        }

    if site_ok and not (payload["contact"]["emails"] or payload["contact"]["phones"]):
        # Pages the crawl already holds. No extra request is spent to look for an address.
        held = [str(value.get("main_text_excerpt") or "")]
        held.extend(str(page.get("main_text_excerpt") or "") for page in pages)
        text = "\n".join(held)
        emails = sorted({m for m in EMAIL_RE.findall(text)})
        phones = sorted({re.sub(r"\s+", "", p) for p in PHONE_RE.findall(text)})
        if emails or phones:
            payload["contact"] = {
                "state": "available",
                "page_url": value.get("final_url"),
                "emails": emails[:5],
                "phones": phones[:5],
                "content_sha256": value.get("content_sha256"),
                "retrieved_at": _now(),
                "found_on": "pages already fetched by this run",
            }

    source_url = value.get("final_url") or normalize_homepage(profile.get("website")) or "https://data.brreg.no/enhetsregisteret/api/enheter"
    content_sha = value.get("content_sha256")
    if payload["careers"].get("content_sha256"):
        payload["sources"].append({"kind": "careers_page", "url": payload["careers"]["page_url"], "content_sha256": payload["careers"]["content_sha256"]})
    if payload["news"].get("content_sha256"):
        payload["sources"].append({"kind": "news_page", "url": payload["news"]["page_url"], "content_sha256": payload["news"]["content_sha256"]})
    if payload["contact"].get("content_sha256"):
        payload["sources"].append({"kind": "contact_page", "url": payload["contact"]["page_url"], "content_sha256": payload["contact"]["content_sha256"]})

    observed = bool(payload["social_handles"] or payload["wikipedia"] or payload["careers"]["openings"] or payload["news"]["items"] or payload["contact"]["emails"] or payload["company_description"])
    record = evidence(
        "footprint",
        "available" if observed else ("not_applicable" if not site_ok and not wikidata_record else "not_found"),
        "company_owned_and_wikidata_cc0",
        source_url,
        value=payload,
        note="Company-owned pages plus Wikidata entries keyed on the organisation number. No third-party platform scraping.",
        content_sha256=content_sha,
    )
    return record, metrics


def _page_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{2,}", "\n", text)


def _now() -> str:
    from .evidence import utc_now

    return utc_now()
