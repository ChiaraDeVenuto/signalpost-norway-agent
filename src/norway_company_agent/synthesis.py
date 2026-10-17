"""Deterministic synthesis and refresh diff.

No model call. Every sentence is assembled from published claims and repeats their evidence
ids, so the summary can be audited sentence by sentence. The refresh path compares claim keys
between two runs and emits typed changes instead of rewriting the profile.
"""
from __future__ import annotations

from typing import Any

SUPPORTED = {
    "legal_name",
    "organisation_number",
    "legal_form",
    "registered_address",
    "municipality",
    "industry",
    "registered_employees",
    "latest_annual_accounts",
    "official_website",
    "company_status",
    "incorporation_date",
}

CHANGE_TYPES = {
    "leadership_role": "new_role",
    "registered_workplace": "new_location",
    "latest_annual_accounts": "new_filing",
    "annual_account_years": "new_filing",
    "job_opening": "new_job",
    "dated_news_item": "new_activity",
    "company_description_from_site": "changed_description",
    "revenue": "changed_financials",
    "annual_result": "changed_financials",
}


def _index(claims: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for claim in claims:
        if claim.get("availability") != "available":
            continue
        key = (str(claim.get("field")), str(claim.get("value")))
        indexed.setdefault(key, claim)
    return indexed


def diff_claims(previous: list[dict[str, Any]] | None, current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not previous:
        return []
    before = _index(previous)
    after = _index(current)
    changes: list[dict[str, Any]] = []
    for key, claim in after.items():
        if key not in before:
            changes.append(
                {
                    "type": CHANGE_TYPES.get(key[0], "new_claim"),
                    "field": key[0],
                    "value": claim.get("value"),
                    "previous_value": None,
                    "first_observed": before.get(key, {}).get("first_observed"),
                    "evidence_ids": claim.get("evidence_ids", []),
                }
            )
    for key, claim in before.items():
        if key not in after:
            changes.append(
                {
                    "type": "removed_or_now_unsupported",
                    "field": key[0],
                    "value": None,
                    "previous_value": claim.get("value"),
                    "evidence_ids": claim.get("evidence_ids", []),
                }
            )
    return changes[:50]


def _value(claims: list[dict[str, Any]], field: str) -> Any:
    for claim in claims:
        if claim.get("field") == field and claim.get("availability") == "available" and claim.get("value") is not None:
            return claim.get("value")
    return None


def _ids(claims: list[dict[str, Any]], field: str) -> list[str]:
    for claim in claims:
        if claim.get("field") == field and claim.get("availability") == "available":
            return claim.get("evidence_ids", [])
    return []


def _money(amount: Any) -> str | None:
    if amount is None:
        return None
    try:
        return "NOK %s" % format(int(round(float(amount))), ",d")
    except (TypeError, ValueError):
        return None


def build_summary(profile: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any]:
    sentences: list[dict[str, Any]] = []
    name = _value(claims, "legal_name") or profile.get("name")
    org = _value(claims, "organisation_number") or profile.get("organisation_number")
    form = _value(claims, "legal_form") or profile.get("legal_form")
    industry = _value(claims, "industry") or profile.get("industry_label")
    municipality = _value(claims, "municipality") or profile.get("municipality")
    employees = _value(claims, "registered_employees") or profile.get("employees")

    identity_tail = [part for part in (("org. %s" % org) if org else None, form) if part]
    sentence = str(name) if name else "This organisation number"
    if identity_tail:
        sentence += " (%s)" % ", ".join(identity_tail)
    if industry:
        sentence += ". It operates in %s" % industry
        if municipality:
            sentence += ", registered in %s" % municipality
        sentence += "."
    else:
        sentence += "."
    sentences.append({"text": sentence, "evidence_ids": _ids(claims, "legal_name") or _ids(claims, "organisation_number")})

    if employees:
        sentences.append(
            {
                "text": "The registry records %s employees." % format(int(employees), ",d"),
                "evidence_ids": _ids(claims, "registered_employees"),
            }
        )

    description = _value(claims, "company_description") or _value(claims, "company_description_from_site")

    purpose = _value(claims, "registered_purpose")
    if purpose:
        sentences.append({"text": "The registered purpose reads: \"%s\"" % str(purpose)[:300], "evidence_ids": _ids(claims, "registered_purpose")})

    if description:
        sentences.append({"text": "The company describes its work this way: \"%s\"" % str(description)[:300], "evidence_ids": _ids(claims, "company_description") or _ids(claims, "company_description_from_site")})

    revenue = _value(claims, "revenue")
    result = _value(claims, "annual_result")
    latest_year = _value(claims, "latest_annual_accounts")
    financial_bits = []
    if revenue is not None:
        financial_bits.append("revenue %s" % _money(revenue))
    if result is not None:
        financial_bits.append("annual result %s" % _money(result))
    if financial_bits:
        period = latest_year or "the latest filed period"
        sentences.append(
            {
                "text": "Filed accounts for %s show %s." % (period, ", ".join(financial_bits)),
                "evidence_ids": _ids(claims, "revenue") or _ids(claims, "annual_result"),
            }
        )
    elif latest_year:
        sentences.append({"text": "Annual accounts are on file for %s; no figures were returned by the account endpoint." % latest_year, "evidence_ids": _ids(claims, "latest_annual_accounts")})

    capital = _value(claims, "share_capital")
    if isinstance(capital, dict):
        amount = _money(capital.get("amount"))
        if amount:
            kind = {"Aksjekapital": "share capital", "Ansvarskapital": "contributed capital", "Organisasjonskapital": "organisational capital"}.get(str(capital.get("type") or ""), "capital")
            sentences.append({"text": "Registered %s: %s." % (kind, amount), "evidence_ids": _ids(claims, "share_capital")})

    leaders = [c.get("value") for c in claims if c.get("field") == "leadership_role" and c.get("availability") == "available"]
    if leaders:
        chief = next((item for item in leaders if item and item.get("role") and "daglig leder" in str(item.get("role")).casefold()), leaders[0])
        names = sorted({str(item.get("name")) for item in leaders if item and item.get("name")})
        text = "%s is %s." % (chief.get("name"), str(chief.get("role")).lower()) if chief and chief.get("role") else None
        if not text and names:
            text = "Registered role holders: %s." % "; ".join(names[:5])
        if text and len(names) > 1:
            text += " The register also lists %d other active role holders." % (len(names) - 1)
        sentences.append({"text": text, "evidence_ids": _ids(claims, "leadership_role")})

    locations = [c for c in claims if c.get("field") == "registered_workplace" and c.get("availability") == "available"]
    if locations:
        first = locations[0].get("value") or {}
        sentences.append(
            {
                "text": "%d registered workplace%s, first listed at %s%s." % (
                    len(locations),
                    "" if len(locations) == 1 else "s",
                    first.get("address") or "the registered address",
                    ", %s" % first.get("municipality") if first.get("municipality") else "",
                ),
                "evidence_ids": _ids(claims, "registered_workplace"),
            }
        )

    website_claims = [c for c in claims if c.get("field") == "official_website" and c.get("availability") == "available" and c.get("value")]
    if website_claims:
        lead = website_claims[0]
        label = "Verified company site" if float(lead.get("confidence") or 0) >= 0.9 else "Homepage listed by the registry"
        sentences.append({"text": "%s: %s" % (label, lead.get("value")), "evidence_ids": _ids(claims, "official_website")})

    jobs = [c for c in claims if c.get("field") == "job_opening" and c.get("availability") == "available"]
    if jobs:
        titles = [str((c.get("value") or ""))[:70] for c in jobs[:4]]
        sentences.append({"text": "Openings published on the careers page: %s." % "; ".join(titles), "evidence_ids": _ids(claims, "job_opening")})
    else:
        careers_claim = next((c for c in claims if c.get("field") == "careers_page"), None)
        if careers_claim and careers_claim.get("availability") == "not_available":
            sentences.append({"text": "The careers page was checked and lists no open roles.", "evidence_ids": careers_claim.get("evidence_ids", [])})

    news = [c for c in claims if c.get("field") == "dated_news_item" and c.get("availability") == "available"]
    if news:
        newest = news[0].get("value") or {}
        sentences.append({"text": "Most recent dated item on the company news page: %s (%s)." % (str(newest.get("title"))[:120], newest.get("date")), "evidence_ids": _ids(claims, "dated_news_item")})

    unknowns = []
    for field in ("official_website", "leadership_role", "revenue", "registered_workplace", "job_opening", "dated_news_item", "contact_email"):
        matching = [c for c in claims if c.get("field") == field]
        if not matching:
            unknowns.append({"field": field, "state": "not_available", "reason": "no claim produced for this field: the source that would carry it did not answer"})
            continue
        unavailable = [c for c in matching if c.get("availability") != "available"]
        if unavailable and len(unavailable) == len(matching):
            unknowns.append({"field": field, "state": unavailable[0].get("availability"), "reason": unavailable[0].get("note") or "source returned nothing for this field"})

    return {
        "headline": sentences[0]["text"] if sentences else "No registry record could be published for this entity.",
        "sentences": sentences,
        "unknowns": unknowns,
        "method": "deterministic_template_v1",
        "generated_from_claims": len(claims),
    }
