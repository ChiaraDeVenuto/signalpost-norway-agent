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
