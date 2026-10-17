"""Contract claims: flatten a researched profile into claim + evidence arrays.

Every claim points at an evidence id. Every evidence row carries source URL, source class,
retrieval time, content hash and a span or selector. Nothing here computes a value that is
not already present in the source record: a missing number stays missing and keeps an
explicit availability state.
"""
from __future__ import annotations

from typing import Any

STATE_MAP = {
    "available": "available",
    "not_found": "not_available",
    "not_applicable": "not_applicable",
    "blocked": "blocked",
    "source_error": "failed",
    "not_fetched": "failed",
    "submission_error": "failed",
}

FINANCIAL_FIELDS = (
    "revenue",
    "operating_result",
    "profit_before_tax",
    "annual_result",
    "assets",
    "equity",
    "debt",
)


def _state(record: dict[str, Any] | None) -> str:
    if not record:
        return "failed"
    return STATE_MAP.get(str(record.get("status")), "failed")


def _flatten_group(nodes: list[dict[str, Any]], depth: int = 0, out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = out if out is not None else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        out.append({**node, "nivaa": node.get("nivaa") or (depth + 1)})
        _flatten_group(node.get("children") or [], depth + 1, out)
    return out


def _empty_state(record: dict[str, Any] | None) -> str:
    """The endpoint answered and the list came back empty: that is not_available, not a failure."""
    state = _state(record)
    return "not_available" if state == "available" else state


def _address(value: Any) -> str | None:
    """CSV rows carry the address as one string; the live API returns a list of lines."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        joined = ", ".join(str(part) for part in value if str(part).strip())
        return joined or None
    return None


def _period(record: dict[str, Any] | None) -> str | None:
    if not record:
        return None
    value = record.get("value") or {}
    records = value.get("records") or []
    if records:
        period = records[0].get("period") or {}
        if period.get("fraDato") and period.get("tilDato"):
            return "%s/%s" % (period["fraDato"], period["tilDato"])
    return record.get("effective_at") or record.get("as_of")


def build_claims(profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_records = profile.get("evidence", {})
    claims: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []

    def add_evidence(evidence_id: str, record: dict[str, Any], span: str, reporting_period: str | None = None) -> str:
        evidence_rows.append(
            {
                "id": evidence_id,
                "source_url": record.get("source_url"),
                "source_class": record.get("source_class") or record.get("source_type"),
                "retrieved_at": record.get("retrieved_at"),
                "content_sha256": record.get("content_sha256"),
                "claim_span": span,
                "reporting_period": reporting_period,
                "status": record.get("status"),
            }
        )
        return evidence_id

    def claim(field: str, value: Any, availability: str, evidence_id: str | None = None, confidence: float | None = None, note: str | None = None) -> None:
        row: dict[str, Any] = {"field": field, "value": value, "availability": availability, "evidence_ids": [evidence_id] if evidence_id else []}
        if confidence is not None:
            row["confidence"] = round(confidence, 3)
        if note:
            row["note"] = note
        claims.append(row)

    registry = evidence_records.get("registry")
    if registry and registry.get("status") == "available":
        raw = registry.get("value") or {}
        identity_map = (
            ("legal_name", raw.get("navn")),
            ("organisation_number", raw.get("organisasjonsnummer")),
            ("legal_form", raw.get("organisasjonsform.beskrivelse")),
            ("legal_form_code", raw.get("organisasjonsform.kode")),
            ("registered_address", _address(raw.get("forretningsadresse.adresse"))),
            ("municipality", raw.get("forretningsadresse.kommune")),
            ("postal_code", raw.get("forretningsadresse.postnummer")),
            ("industry_code", raw.get("naeringskode1.kode")),
            ("industry", raw.get("naeringskode1.beskrivelse")),
            ("registered_employees", int(raw["antallAnsatte"]) if str(raw.get("antallAnsatte") or "").isdigit() else None),
            ("latest_annual_accounts", raw.get("sisteInnsendteAarsregnskap")),
            ("registry_website", raw.get("hjemmeside") or None),
            ("contact_email", raw.get("epostadresse") or None),
            ("company_status", "bankrupt" if raw.get("konkurs") == "true" else "liquidating" if raw.get("underAvvikling") == "true" else "active"),
            ("incorporation_date", raw.get("stiftelsesdato") or None),
        )
        for index, (field, value) in enumerate(identity_map):
            if value in (None, "", []):
                continue
            evidence_id = add_evidence("ev-registry-%d" % index, registry, "row[%s].%s" % (raw.get("organisasjonsnummer"), field))
            claim(field, value, "available", evidence_id)

    live = evidence_records.get("registry_live")
    if live and live.get("status") == "available":
        value = live.get("value") or {}
        already_claimed = {c.get("field") for c in claims if c.get("availability") == "available"}
        live_map = (
            ("legal_name_live", "name"),
            ("registered_employees", "employees"),
            ("official_website", "website"),
            ("latest_annual_accounts", "latest_submitted_accounts"),
            ("registered_address", "address_line"),
            ("municipality", "municipality"),
            ("contact_email", "email"),
            ("incorporation_date", "incorporation_date"),
        )
        for index, (field, source_key) in enumerate(live_map):
            if value.get(source_key) in (None, "") or (field in already_claimed):
                continue
            evidence_id = add_evidence("ev-live-%d" % index, live, "body.%s" % source_key)
            claim(field, value[source_key], "available", evidence_id)

    financials = evidence_records.get("financials")
    if financials:
        state = _state(financials)
        reporting_period = _period(financials)
        records = (financials.get("value") or {}).get("records") or []
        if state == "available" and records:
            evidence_id = add_evidence("ev-financials", financials, "records[0]", reporting_period)
            for field in FINANCIAL_FIELDS:
                amount = records[0].get(field)
                if amount is None:
                    claim(field, None, "not_available", evidence_id, note="not present in the filed accounts")
                    continue
                claim(field, amount, "available", evidence_id, note="NOK, period %s" % reporting_period if reporting_period else "NOK")
        else:
            evidence_id = add_evidence("ev-financials-unavailable", financials, "records[]")
            claim("annual_accounts", None, state, evidence_id, note=financials.get("note") or "no filed accounts returned for this entity")

    history = evidence_records.get("financial_history")
    if history:
        value = history.get("value") or {}
        years = value.get("years") or []
        if years:
            evidence_id = add_evidence("ev-financial-history", history, "years")
            claim("annual_account_years", years, "available", evidence_id)
            for year in years[:6]:
                claim("annual_account_pdf_%s" % year, BRREG_PDF(history.get("source_url"), year), "available", evidence_id)
        else:
            claim("annual_account_years", None, _state(history), add_evidence("ev-financial-history-unavailable", history, "years"))

    roles = evidence_records.get("roles")
    if roles:
        items = (roles.get("value") or {}).get("roles") or []
        active = [item for item in items if not item.get("inactive") and item.get("name")]
        if active:
            for index, item in enumerate(active[:12]):
                evidence_id = add_evidence("ev-roles-%d" % index, roles, "roles[%d] (%s)" % (index, item.get("role_code") or item.get("role")), item.get("last_changed"))
                claim("leadership_role", {"name": item.get("name"), "role": item.get("role"), "group": item.get("group"), "last_changed": item.get("last_changed")}, "available", evidence_id)
        else:
            claim("leadership_role", None, _empty_state(roles), None, note="the roles endpoint answered and lists no active role holder for this entity")

    locations = evidence_records.get("locations")
    if locations:
        items = (locations.get("value") or {}).get("locations") or []
        if items:
            for index, item in enumerate(items[:25]):
                address = item.get("address") or {}
                line = ", ".join(address.get("adresse") or [])
                if not line:
                    line = " ".join(part for part in (address.get("postnummer"), address.get("poststed")) if part)
                evidence_id = add_evidence("ev-locations-%d" % index, locations, "locations[%d]" % index)
                claim(
                    "registered_workplace",
                    {"organisation_number": item.get("organisation_number"), "name": item.get("name"), "address": line, "municipality": address.get("kommune"), "postal_code": address.get("postnummer")},
                    "available",
                    evidence_id,
                )
        else:
            claim("registered_workplace", None, _empty_state(locations), None, note="the subunit endpoint answered and lists no registered workplace for this entity")

    group = evidence_records.get("group")
    if group and group.get("status") == "available":
        value = group.get("value") or {}
        parent = value.get("parent") or value.get("overordnetEnhet") or {}
        if isinstance(parent, dict) and parent.get("navn"):
            evidence_id = add_evidence("ev-group-parent", group, "parent")
            claim(
                "group_parent",
                {"name": parent.get("navn"), "organisation_number": parent.get("organisasjonsnummer")},
                "available",
                evidence_id,
                note=parent.get("knytningsform", {}).get("beskrivelse") if isinstance(parent.get("knytningsform"), dict) else None,
            )
        children = _flatten_group(value.get("children") or [])
        if children:
            for index, child in enumerate(children[:40]):
                evidence_id = add_evidence(
                    "ev-group-%d" % index,
                    group,
                    "children[%d] %s" % (index, child.get("organisasjonsnummer") or child.get("navn")),
                    child.get("dato"),
                )
                claim(
                    "group_subsidiary",
                    {
                        "name": child.get("navn"),
                        "organisation_number": child.get("organisasjonsnummer"),
                        "share": child.get("grunnlag"),
                        "link": child.get("knytningsform"),
                        "since": child.get("dato"),
                        "level": child.get("nivaa"),
                    },
                    "available",
                    evidence_id,
                )
        elif not parent:
            claim("group_subsidiary", None, "not_available", None, note="the group endpoint answered and lists no parent and no subsidiary for this entity")

    website = evidence_records.get("website")
    if website:
        value = website.get("value") or {}
        if website.get("status") == "available":
            assessment = value.get("identity_assessment") or {}
            note = str(assessment.get("method") or "")
            if value.get("seed_source"):
                note = ("url seeded from %s; %s" % (value["seed_source"], note)).strip("; ")
            evidence_id = add_evidence("ev-website", website, "final_url")
            claim("official_website", value.get("final_url"), "available", evidence_id, confidence=float(assessment.get("score") or 0.9), note=note or None)
            if value.get("description"):
                claim("company_description", value.get("description"), "available", add_evidence("ev-website-description", website, "meta[name=description]"))
            elif value.get("main_text_excerpt"):
                claim("company_description", value.get("main_text_excerpt")[:400], "available", add_evidence("ev-website-text", website, "main_text_excerpt"))
            for index, page in enumerate(value.get("pages") or []):
                evidence_id = add_evidence("ev-website-page-%d" % index, website, "pages[%d] %s" % (index, page.get("url")))
                claim("company_page", {"url": page.get("url"), "title": page.get("title")}, "available", evidence_id)
        else:
            claim("official_website", None, _state(website), None, note=website.get("note"))

    wikidata = evidence_records.get("wikidata")
    if wikidata:
        record = (wikidata.get("value") or {}).get("records", {}).get(profile.get("organisation_number"))
        if record:
            evidence_id = add_evidence("ev-wikidata", wikidata, record.get("item") or "record")
            for article_language, url in (record.get("articles") or {}).items():
                claim("wikipedia_article_%s" % article_language, url, "available", evidence_id)
            if record.get("label"):
                claim("wikidata_label", record.get("label"), "available", evidence_id, note=record.get("description"))
            if record.get("inception"):
                claim("wikidata_inception", record.get("inception")[:10], "available", evidence_id)
            if record.get("employees"):
                claim("wikidata_employees", int(record["employees"]) if str(record["employees"]).isdigit() else record["employees"], "available", evidence_id, note="organization-level figure, not a registry count")
            for platform, handles in (record.get("social") or {}).items():
                for handle in handles[:1]:
                    claim("social_profile_%s" % platform, handle, "available", evidence_id, note="Wikidata item keyed on the organisation number")
            if record.get("coordinates"):
                claim("wikidata_coordinates", record.get("coordinates"), "available", evidence_id)
        else:
            claim("wikidata_record", None, "not_available", None, note="no Wikidata item carries this organisation number")

    footprint = evidence_records.get("footprint")
    if footprint:
        value = footprint.get("value") or {}
        status = footprint.get("status")
        if status == "available":
            careers = value.get("careers") or {}
            if careers.get("page_url"):
                evidence_id = add_evidence("ev-careers", footprint, "careers.page_url %s" % careers.get("page_url"))
                claim("careers_page", careers.get("page_url"), "available" if careers.get("openings") else careers.get("state") or "not_available", evidence_id)
                for index, opening in enumerate(careers.get("openings") or []):
                    claim("job_opening", opening, "available", add_evidence("ev-careers-%d" % index, footprint, careers.get("page_url")))
            else:
                claim("careers_page", None, "not_available", None, note="no careers link found on the verified company site")

            news = value.get("news") or {}
            if news.get("page_url"):
                evidence_id = add_evidence("ev-news", footprint, "news.page_url %s" % news.get("page_url"))
                claim("news_page", news.get("page_url"), "available" if news.get("items") else news.get("state") or "not_available", evidence_id)
                for item in news.get("items") or []:
                    claim("dated_news_item", item, "available", add_evidence("ev-news-item-%s" % item.get("date", "x"), footprint, news.get("page_url")))
            else:
                claim("news_page", None, "not_available", None, note="no news link found on the verified company site")

            contact = value.get("contact") or {}
            if contact.get("emails") or contact.get("phones"):
                evidence_id = add_evidence("ev-contact", footprint, contact.get("page_url") or "company site")
                for email in contact.get("emails") or []:
                    claim("contact_email", email, "available", evidence_id)
                for phone in contact.get("phones") or []:
                    claim("contact_phone", phone, "available", evidence_id)
            else:
                claim("contact_email", None, "not_available" if str(contact.get("state")) in ("not_checked", "None") else contact.get("state"), None, note="no contact address was published on the verified company site")

            for index, handle in enumerate(value.get("social_handles") or []):
                claim("social_handle_%s" % handle.get("platform"), handle.get("url") or handle.get("handle"), "available", add_evidence("ev-footprint-social-%d" % index, footprint, handle.get("source")))
            for language, url in (value.get("wikipedia") or {}).items():
                claim("wikipedia_article_%s" % language, url, "available", add_evidence("ev-footprint-wiki-%s" % language, footprint, url))
            if value.get("company_description"):
                claim("company_description_from_site", value["company_description"]["text"], "available", add_evidence("ev-footprint-description", footprint, value["company_description"]["source"]))
        else:
            claim("public_footprint", None, STATE_MAP.get(status, "failed"), None, note=footprint.get("note"))

    return claims, evidence_rows


def BRREG_PDF(source_url: str | None, year: str) -> str:
    return "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/{year}".format(
        org=str(source_url or "").rstrip("/").split("/")[-1], year=year
    )
