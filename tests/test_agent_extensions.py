"""Tests for the competition extensions: Wikidata lookup, claims, synthesis, seeding.

Everything here runs offline. Network behaviour is covered by the 100-company smoke run
recorded in docs/SMOKE-TEST.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from norway_company_agent.claims import build_claims  # noqa: E402
from norway_company_agent.evidence import evidence  # noqa: E402
from norway_company_agent.synthesis import build_summary, diff_claims  # noqa: E402
from norway_company_agent.wikidata import _aggregate, build_query, rank_websites  # noqa: E402
from run_agent import seed_from_registry_email  # noqa: E402


def _profile(**evidence_records: dict) -> dict:
    return {
        "organisation_number": "912345678",
        "name": "EXAMPLE AS",
        "legal_form": "AS",
        "employees": 4,
        "municipality": "OSLO",
        "industry_label": "Programvareutvikling",
        "website": "",
        "latest_submitted_accounts": "2025",
        "evidence": evidence_records,
        "run_metrics": {"requests": 0, "bytes": 0, "latencies_ms": []},
    }


def test_query_projects_every_optional_variable():
    query = build_query(["912345678"])
    assert '"912345678"' in query
    for variable in ("official_website", "facebook", "instagram", "coordinates", "inception", "employees", "industryLabel", "legalFormLabel"):
        assert "?%s" % variable in query


def test_aggregate_keeps_only_rows_carrying_the_requested_number():
    rows = [
        {"org": {"value": "912345678"}, "item": {"value": "http://www.wikidata.org/entity/Q1"},
         "itemLabel": {"value": "Example AS"}, "official_website": {"value": "https://example.no/"}},
        {"org": {"value": "999999999"}, "item": {"value": "http://www.wikidata.org/entity/Q2"},
         "itemLabel": {"value": "Someone Else"}, "official_website": {"value": "https://other.no/"}},
    ]
    record = _aggregate(rows, "912345678")
    assert record is not None
    assert record["label"] == "Example AS"
    assert record["official_websites"] == ["https://example.no/"]
    assert _aggregate(rows, "987654321") is None


def test_rank_websites_prefers_the_corporate_root():
    candidates = [
        "https://example.no/en/contact",
        "https://example.com",
        "https://example.pl",
        "https://www.example.com/about",
    ]
    ranked = rank_websites(candidates, "EXAMPLE ASA")
    assert ranked[0] == "https://example.com"


def test_seed_from_registry_email_skips_free_mail_hosts():
    assert seed_from_registry_email("post@appelx.com") == "https://appelx.com"
    assert seed_from_registry_email("someone@gmail.com") is None
    assert seed_from_registry_email("post@outlook.no") is None
    assert seed_from_registry_email(None) is None
    assert seed_from_registry_email("not-an-address") is None


def test_empty_registry_list_is_not_available_with_a_null_value():
    roles = evidence(
        "roles",
        "available",
        "official_roles",
        "https://data.brreg.no/enhetsregisteret/api/enheter/912345678/roller",
        value={"roles": []},
    )
    claims, rows = build_claims(_profile(roles=roles))
    leadership = [claim for claim in claims if claim["field"] == "leadership_role"]
    assert leadership and leadership[0]["availability"] == "not_available"
    assert leadership[0]["value"] is None
    assert not leadership[0]["evidence_ids"]


def test_csv_address_stays_one_string():
    registry = evidence(
        "registry",
        "available",
        "official_registry_bulk",
        "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
        value={
            "organisasjonsnummer": "912345678",
            "navn": "EXAMPLE AS",
            "organisasjonsform.kode": "AS",
            "organisasjonsform.beskrivelse": "Aksjeselskap",
            "forretningsadresse.adresse": "Storgata 1",
            "forretningsadresse.kommune": "OSLO",
            "forretningsadresse.postnummer": "0155",
            "naeringskode1.kode": "62.010",
            "naeringskode1.beskrivelse": "Programvareutvikling",
            "antallAnsatte": "4",
            "sisteInnsendteAarsregnskap": "2025",
            "stiftelsesdato": "1999-01-01",
            "konkurs": "false",
            "underAvvikling": "false",
        },
    )
    claims, _ = build_claims(_profile(registry=registry))
    address = next(claim for claim in claims if claim["field"] == "registered_address")
    assert address["value"] == "Storgata 1"
    employees = next(claim for claim in claims if claim["field"] == "registered_employees")
    assert employees["value"] == 4


def test_every_summary_sentence_carries_evidence_ids():
    registry = evidence(
        "registry",
        "available",
        "official_registry_bulk",
        "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
        value={"organisasjonsnummer": "912345678", "navn": "EXAMPLE AS", "organisasjonsform.kode": "AS",
               "organisasjonsform.beskrivelse": "Aksjeselskap", "forretningsadresse.kommune": "OSLO",
               "naeringskode1.beskrivelse": "Programvareutvikling", "antallAnsatte": "4"},
    )
    claims, _ = build_claims(_profile(registry=registry))
    summary = build_summary(_profile(registry=registry), claims)
    assert summary["sentences"]
    assert summary["headline"]
    for sentence in summary["sentences"]:
        assert "evidence_ids" in sentence
        assert sentence["text"].strip()
    assert summary["method"] == "deterministic_template_v1"


def test_refresh_diff_reports_typed_changes():
    before = [{"field": "leadership_role", "value": {"name": "Old Name", "role": "Daglig leder"},
               "availability": "available", "evidence_ids": ["ev-roles-0"]}]
    after = [{"field": "leadership_role", "value": {"name": "New Name", "role": "Daglig leder"},
              "availability": "available", "evidence_ids": ["ev-roles-0"]},
             {"field": "dated_news_item", "value": {"title": "Contract signed", "date": "2026-09-04"},
              "availability": "available", "evidence_ids": ["ev-news-item-2026-09-04"]}]
    changes = diff_claims(before, after)
    types = {change["type"] for change in changes}
    assert "new_role" in types
    assert "new_activity" in types
    assert any(change["type"] == "removed_or_now_unsupported" for change in changes)
    assert diff_claims([], after) == []


def test_claims_without_a_source_never_count_as_available():
    registry = evidence("registry", "not_found", "official_registry_bulk",
                        "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
                        source_row_key="999999999")
    claims, rows = build_claims(_profile(registry=registry))
    assert all(claim["availability"] != "available" for claim in claims)
    assert all(row["source_url"] for row in rows)


def _website(seed_source: str | None, score: float, publishable: bool, reasons: list[str], url: str = "https://brand.example.no/") -> dict:
    return evidence(
        "website",
        "available",
        "company_website",
        url,
        value={
            "final_url": url,
            "seed_source": seed_source,
            "description": "A company that does things.",
            "main_text_excerpt": "A company that does things, at length, with enough words to count as substantive copy.",
            "pages": [{"url": url + "about", "title": "About"}],
            "identity_assessment": {"score": score, "publishable": publishable, "reasons": reasons,
                                     "method": "deterministic_name_org_evidence_v2"},
        },
    )


def test_mail_seeded_site_without_gate_confirmation_is_withheld():
    website = _website(
        "registry contact e-mail domain (same registry row as the organisation number)",
        0.3, False, ["registry-linked URL lacks strong exact-entity identity evidence"],
    )
    claims, _ = build_claims(_profile(website=website))
    site = next(claim for claim in claims if claim["field"] == "official_website")
    assert site["availability"] == "ambiguous"
    assert site["value"] == "https://brand.example.no/"
    assert site["confidence"] == 0.3
    assert "ambiguous" in site["note"]
    assert not [claim for claim in claims if claim["field"] == "company_description"]
    assert not [claim for claim in claims if claim["field"] == "company_page"]


def test_parked_page_is_never_published():
    website = _website("registry contact e-mail domain (same registry row as the organisation number)",
                       0.1, False, ["captured page is a parked, for-sale, or generic hosting placeholder"])
    claims, _ = build_claims(_profile(website=website))
    site = next(claim for claim in claims if claim["field"] == "official_website")
    assert site["availability"] == "not_available"
    assert "parked" in site["note"]


def test_registry_listed_homepage_publishes_with_its_low_confidence():
    website = _website(None, 0.3, False, ["registry-linked URL lacks strong exact-entity identity evidence"])
    claims, _ = build_claims(_profile(website=website))
    site = next(claim for claim in claims if claim["field"] == "official_website")
    assert site["availability"] == "available"
    assert site["confidence"] == 0.3
    assert [claim for claim in claims if claim["field"] == "company_description"]
    summary = build_summary(_profile(website=website), claims)
    sentence = next(item["text"] for item in summary["sentences"] if "homepage" in item["text"].casefold())
    assert "registry" in sentence.casefold()


def test_a_second_claim_never_repeats_the_same_host():
    registry = evidence(
        "registry",
        "available",
        "official_registry_bulk",
        "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
        value={"organisasjonsnummer": "912345678", "navn": "EXAMPLE AS", "hjemmeside": "www.example.no"},
    )
    website = _website(None, 1.0, True, ["exact organisation number appears in homepage identity evidence"],
                       url="https://www.example.no/")
    claims, _ = build_claims(_profile(registry=registry, website=website))
    published = [claim for claim in claims if claim["field"] == "official_website" and claim["availability"] == "available"]
    assert len(published) == 1
    assert [claim for claim in claims if claim["field"] == "registry_website"][0]["value"] == "www.example.no"


def test_live_registry_website_wins_over_a_redundant_crawl():
    live = evidence("registry_live", "available", "official_registry_live",
                    "https://data.brreg.no/enhetsregisteret/api/enheter/912345678",
                    value={"name": "EXAMPLE AS", "website": "www.example.no"})
    website = _website(None, 0.3, False, ["registry-linked URL lacks strong exact-entity identity evidence"],
                       url="https://www.example.no/")
    claims, _ = build_claims(_profile(registry_live=live, website=website))
    published = [claim for claim in claims if claim["field"] == "official_website" and claim["availability"] == "available"]
    assert len(published) == 1
    assert published[0]["value"] == "www.example.no"


def test_registry_row_publishes_capital_purpose_sector_and_contact_details():
    registry = evidence(
        "registry",
        "available",
        "official_registry_bulk",
        "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
        value={
            "organisasjonsnummer": "912345678",
            "navn": "EXAMPLE AS",
            "kapital.belop": "100000.00",
            "kapital.valuta": "NOK",
            "kapital.type": "Aksjekapital",
            "kapital.antallAksjer": "50",
            "vedtektsfestetFormaal": "Eie og forvalte faste eiendommer.",
            "aktivitet": "Utleie av næringsbygg.",
            "institusjonellSektorkode.beskrivelse": "Private aksjeselskaper mv.",
            "vedtektsdato": "2013-09-10",
            "registreringsdatoenhetsregisteret": "2013-11-13",
            "maalform": "Bokmål",
            "postadresse.adresse": "c/o Ole Ronny Sandbekk\nØvre Langelandsveg 5",
            "postadresse.postnummer": "2213",
            "postadresse.poststed": "KONGSVINGER",
            "postadresse.land": "Norge",
            "registrertIMvaRegisteret": "true",
            "telefon": "22 00 00 00",
            "overordnetEnhet": "987654321",
        },
    )
    claims, rows = build_claims(_profile(registry=registry))
    published = {claim["field"]: claim for claim in claims if claim["availability"] == "available"}
    assert published["share_capital"]["value"] == {"amount": 100000.0, "currency": "NOK", "type": "Aksjekapital", "number_of_shares": 50}
    assert published["registered_purpose"]["value"] == "Eie og forvalte faste eiendommer."
    assert published["registered_activity"]["value"] == "Utleie av næringsbygg."
    assert published["registered_sector"]["value"] == "Private aksjeselskaper mv."
    assert published["articles_adopted_date"]["value"] == "2013-09-10"
    assert published["register_registration_date"]["value"] == "2013-11-13"
    assert published["language_form"]["value"] == "Bokmål"
    assert published["postal_address"]["value"] == "c/o Ole Ronny Sandbekk Øvre Langelandsveg 5, 2213 KONGSVINGER"
    assert published["vat_registered"]["value"] is True
    assert published["contact_phone"]["value"] == "22 00 00 00"
    assert published["parent_organisation_number"]["value"] == "987654321"
    spans = {row["id"]: row["claim_span"] for row in rows}
    assert spans[published["share_capital"]["evidence_ids"][0]] == "row[912345678].kapital.belop"
    assert spans[published["legal_name"]["evidence_ids"][0]] == "row[912345678].navn"


def test_identical_purpose_and_activity_publish_once():
    registry = evidence(
        "registry",
        "available",
        "official_registry_bulk",
        "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
        value={"organisasjonsnummer": "912345678", "navn": "EXAMPLE AS",
               "vedtektsfestetFormaal": "Utleie av eiendom.", "aktivitet": "Utleie av eiendom."},
    )
    claims, _ = build_claims(_profile(registry=registry))
    assert len([claim for claim in claims if claim["field"] == "registered_purpose"]) == 1
    assert not [claim for claim in claims if claim["field"] == "registered_activity"]


def test_unconfirmed_crawl_of_a_registry_listed_host_adds_no_second_claim():
    registry = evidence(
        "registry",
        "available",
        "official_registry_bulk",
        "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
        value={"organisasjonsnummer": "912345678", "navn": "EXAMPLE AS", "hjemmeside": "www.example.no"},
    )
    website = _website("registry contact e-mail domain (same registry row as the organisation number)",
                       0.3, False, ["registry-linked URL lacks strong exact-entity identity evidence"],
                       url="https://www.example.no/")
    claims, _ = build_claims(_profile(registry=registry, website=website))
    assert not [claim for claim in claims if claim["field"] == "official_website"]
    registry_site = next(claim for claim in claims if claim["field"] == "registry_website")
    assert registry_site["availability"] == "available"
    assert registry_site["value"] == "www.example.no"
    assert not [claim for claim in claims if claim["field"] == "company_description"]


def test_a_checked_contact_page_without_addresses_is_not_available():
    footprint = evidence(
        "footprint",
        "available",
        "company_website",
        "https://www.example.no/",
        value={"contact": {"emails": [], "phones": [], "state": "available", "page_url": "https://www.example.no/"}},
    )
    claims, _ = build_claims(_profile(footprint=footprint))
    contact = next(claim for claim in claims if claim["field"] == "contact_email")
    assert contact["availability"] == "not_available"
    assert contact["value"] is None
