#!/usr/bin/env python3
"""One-command Signalpost runner.

Reads a batch of organisation numbers, researches each company, and writes exactly one
terminal envelope per input. The envelope is written even when a source fails, a module
exceeds its budget or a company cannot be found: a missing row is the only outcome that
cannot be scored.

Usage:
    python scripts/run_agent.py --organisations batch.jsonl --output out/envelopes.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import read_organisation_inputs, terminal_envelope  # noqa: E402
from norway_company_agent.claims import build_claims  # noqa: E402
from norway_company_agent.evidence import evidence, utc_now  # noqa: E402
from norway_company_agent.footprint import build_footprint  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.official import fetch_official_modules  # noqa: E402
from norway_company_agent.sampling import iter_bulk  # noqa: E402
from norway_company_agent.synthesis import build_summary, diff_claims  # noqa: E402
from norway_company_agent.website import fetch_website, normalize_homepage  # noqa: E402
from norway_company_agent.wikidata import lookup_organisations  # noqa: E402

BULK_SOURCE = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv"
OFFICIAL_MODULES = ("registry_live", "financials", "roles", "group", "locations")

# Free mail providers and employer domains that do not identify the entity itself.
GENERIC_MAIL_HOSTS = {
    "gmail.com", "gmail.no", "googlemail.com", "hotmail.com", "hotmail.no", "outlook.com",
    "outlook.no", "live.com", "live.no", "yahoo.com", "yahoo.no", "icloud.com", "me.com",
    "aol.com", "proton.me", "protonmail.com", "mail.com", "online.no", "powertech.net",
    "telenor.net", "getmail.no", "nextgentel.no", "bredbnd2.no", "telia.com", "utsikten.no",
    "webhuset.no", "easyweb.no", "domeneshop.no", "chello.no", "compass-network.no",
}

EMAIL_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}$")


def seed_from_registry_email(email: str | None) -> str | None:
    """Turn the registry's own contact e-mail into a website candidate.

    The address comes from the same registry row as the organisation number, so the candidate
    belongs to this entity by construction. Whether it really does is decided later by the
    identity gate on the crawled page, not here.
    """
    if not email or "@" not in str(email):
        return None
    domain = str(email).rsplit("@", 1)[1].strip().casefold().split(">")[0]
    if domain in GENERIC_MAIL_HOSTS or not EMAIL_DOMAIN_RE.match(domain):
        return None
    return "https://" + domain



def log(message: str) -> None:
    print("[%s] %s" % (utc_now(), message), flush=True)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def load_bulk(path: Path | None, wanted: set[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Stream the frozen registry snapshot once. Missing organisations fall back to the live API."""
    if path is None or not path.exists():
        return {}, {"loaded": 0, "source": "none", "note": "bulk snapshot unavailable"}
    found: dict[str, dict[str, Any]] = {}
    scanned = 0
    for record in iter_bulk(path):
        scanned += 1
        org = record["organisation_number"]
        if org in wanted:
            found[org] = record.get("raw") or {}
        if len(found) == len(wanted):
            break
    return found, {"loaded": len(found), "scanned": scanned, "source": str(path)}


def read_batch(path_argument: str | None) -> list[dict[str, Any]]:
    candidate = path_argument or os.environ.get("SIGNALPOST_BATCH")
    if not candidate:
        raise SystemExit("No batch file. Pass --organisations or set SIGNALPOST_BATCH.")
    return read_organisation_inputs(candidate)


def minimal_profile(organisation_number: str) -> dict[str, Any]:
    return {
        "organisation_number": organisation_number,
        "name": None,
        "legal_form": None,
        "employees": None,
        "municipality": None,
        "industry_label": None,
        "website": "",
        "latest_submitted_accounts": None,
        "evidence": {},
        "run_metrics": {"requests": 0, "bytes": 0, "latencies_ms": []},
    }


def apply_registry_row(profile: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    profile["name"] = raw.get("navn") or profile.get("name")
    profile["legal_form"] = (raw.get("organisasjonsform.kode") or profile.get("legal_form")) or None
    employees_raw = str(raw.get("antallAnsatte") or "")
    profile["employees"] = int(employees_raw) if employees_raw.isdigit() else profile.get("employees")
    profile["municipality"] = raw.get("forretningsadresse.kommune") or profile.get("municipality")
    profile["industry_label"] = raw.get("naeringskode1.beskrivelse") or profile.get("industry_label")
    profile["website"] = raw.get("hjemmeside") or profile.get("website") or ""
    profile["latest_submitted_accounts"] = raw.get("sisteInnsendteAarsregnskap") or profile.get("latest_submitted_accounts")
    profile["bankrupt"] = str(raw.get("konkurs") or "").lower() == "true"
    profile["liquidating"] = str(raw.get("underAvvikling") or "").lower() == "true"
    return profile


def research_company(
    organisation_number: str,
    raw_row: dict[str, Any] | None,
    wikidata_record: dict[str, Any] | None,
    wikidata_evidence: dict[str, Any],
    *,
    run_id: str,
    started_at: str,
    budget_seconds: float,
    with_history: bool,
    snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    """Research one company. Always returns a terminal envelope."""
    company_started = time.monotonic()
    deadline = company_started + budget_seconds
    profile = minimal_profile(organisation_number)
    errors: list[dict[str, str]] = []

    if raw_row:
        profile = apply_registry_row(profile, raw_row)
        registry_record = evidence(
            "registry",
            "available",
            "official_registry_bulk",
            BULK_SOURCE,
            value=raw_row,
            content_sha256=snapshot_sha256,
            source_row_key=organisation_number,
        )
        profile["evidence"]["registry"] = registry_record
    else:
        profile["evidence"]["registry"] = evidence(
            "registry",
            "not_found",
            "official_registry_bulk",
            BULK_SOURCE,
            note="Organisation number not present in the frozen bulk snapshot; the live registry API was queried instead.",
            source_row_key=organisation_number,
        )

    if time.monotonic() < deadline:
        try:
            modules, module_metrics = fetch_official_modules(organisation_number, set(OFFICIAL_MODULES) | ({"financial_history"} if with_history else set()))
            profile["evidence"].update(modules)
            for result in module_metrics:
                profile["run_metrics"]["requests"] = profile["run_metrics"].get("requests", 0) + 1
                profile["run_metrics"]["bytes"] = profile["run_metrics"].get("bytes", 0) + int(getattr(result, "bytes_received", 0) or 0)
                latency = int(getattr(result, "elapsed_ms", 0) or 0)
                if latency:
                    profile["run_metrics"]["latencies_ms"] = profile["run_metrics"].get("latencies_ms", []) + [latency]
            for module, record in modules.items():
                if record.get("status") == "source_error":
                    errors.append({"module": module, "error": str(record.get("note"))[:200]})
        except Exception as exc:
            errors.append({"module": "official_modules", "error": "%s: %s" % (type(exc).__name__, str(exc)[:200])})
    else:
        errors.append({"module": "official_modules", "error": "per-company budget exhausted before registry call"})

    registry_live = profile["evidence"].get("registry_live") or {}
    if registry_live.get("status") == "available" and registry_live.get("value"):
        live = registry_live["value"]
        if not profile.get("name"):
            profile["name"] = live.get("name")
        if not profile.get("website") and live.get("website"):
            profile["website"] = live["website"]
        if not profile.get("legal_form"):
            profile["legal_form"] = live.get("legal_form")
        if profile.get("employees") is None and live.get("employees") is not None:
            profile["employees"] = live.get("employees")

    seed_source = None
    if not normalize_homepage(profile.get("website")):
        live_value = registry_live.get("value") or {}
        seeded = seed_from_registry_email((raw_row or {}).get("epostadresse")) or seed_from_registry_email(live_value.get("email"))
        if seeded:
            profile["website"] = seeded
            seed_source = "registry contact e-mail domain (same registry row as the organisation number)"
        elif wikidata_record:
            candidate = (wikidata_record.get("official_websites") or [None])[0]
            if candidate:
                profile["website"] = candidate
                seed_source = "Wikidata P856 on the item keyed by this organisation number"

    if time.monotonic() < deadline:
        try:
            website_record, website_metrics = fetch_website(normalize_homepage(profile.get("website")), timeout=12.0)
            if seed_source and website_record.get("status") == "not_found":
                seeded_url = normalize_homepage(profile.get("website")) or ""
                host = (urllib.parse.urlparse(seeded_url).hostname or "")
                if host and not host.startswith("www."):
                    retry_url = "https://www." + host
                    retry_record, retry_metrics = fetch_website(retry_url, timeout=10.0)
                    website_record, website_metrics = retry_record, retry_metrics
                    if retry_record.get("status") == "available":
                        seed_source = "%s; the apex host did not answer so the www host was used" % seed_source
            if website_record.get("status") == "blocked" and "did not resolve" in str(website_record.get("note") or ""):
                # A host that does not exist is a dead reference, not a policy refusal.
                website_record["status"] = "source_error"
                website_record["note"] = "dns: " + str(website_record.get("note"))
            gated = apply_website_identity_gate(profile, website_record)
            profile["evidence"]["website"] = gated["website"]
            if seed_source and isinstance(profile["evidence"]["website"].get("value"), dict):
                profile["evidence"]["website"]["value"]["seed_source"] = seed_source
                if "wikidata" in seed_source.lower():
                    profile["evidence"]["website"]["source_class"] = "wikidata_cc0_seeded_company_website"
            profile["run_metrics"]["requests"] = profile["run_metrics"].get("requests", 0) + website_metrics.get("requests", 0)
            profile["run_metrics"]["bytes"] = profile["run_metrics"].get("bytes", 0) + website_metrics.get("bytes", 0)
            profile["run_metrics"]["latencies_ms"] = profile["run_metrics"].get("latencies_ms", []) + list(website_metrics.get("latencies_ms") or [])
        except Exception as exc:
            errors.append({"module": "website", "error": "%s: %s" % (type(exc).__name__, str(exc)[:200])})
            profile["evidence"]["website"] = evidence("website", "source_error", "registry_linked_company_website", normalize_homepage(profile.get("website")) or BULK_SOURCE, note=str(exc)[:200])
    else:
        profile["evidence"]["website"] = evidence("website", "not_fetched", "registry_linked_company_website", normalize_homepage(profile.get("website")) or BULK_SOURCE, note="per-company budget exhausted before site crawl")

    if wikidata_record or profile["evidence"].get("website", {}).get("status") == "available":
        if time.monotonic() < deadline:
            try:
                footprint_record, footprint_metrics = build_footprint(profile, wikidata_record)
                profile["evidence"]["footprint"] = footprint_record
                profile["run_metrics"]["requests"] = profile["run_metrics"].get("requests", 0) + footprint_metrics.get("requests", 0)
                profile["run_metrics"]["bytes"] = profile["run_metrics"].get("bytes", 0) + footprint_metrics.get("bytes", 0)
                profile["run_metrics"]["latencies_ms"] = profile["run_metrics"].get("latencies_ms", []) + list(footprint_metrics.get("latencies_ms") or [])
                for item in footprint_metrics.get("errors") or []:
                    errors.append({"module": "footprint", "error": "%s: %s" % (item.get("url"), item.get("error"))})
            except Exception as exc:
                errors.append({"module": "footprint", "error": "%s: %s" % (type(exc).__name__, str(exc)[:200])})

    if wikidata_evidence:
        own_record = wikidata_record
        per_company = dict(wikidata_evidence)
        shared_value = dict(wikidata_evidence.get("value") or {})
        shared_value["records"] = {organisation_number: own_record} if own_record else {}
        shared_value["matched_this_entity"] = bool(own_record)
        per_company["value"] = shared_value
        per_company["status"] = "available" if own_record else "not_found"
        per_company["note"] = (
            "Exact-entity lookup keyed on P2333 (Norwegian organisation number). "
            + ("This organisation number is carried by a Wikidata item." if own_record else "No Wikidata item carries this organisation number.")
        )
        profile["evidence"]["wikidata"] = per_company

    claims, evidence_rows = build_claims(profile)
    summary = build_summary(profile, claims)

    completed_at = utc_now()
    envelope = terminal_envelope(profile, run_id=run_id, modules=sorted(profile["evidence"].keys()), started_at=started_at, completed_at=completed_at)
    latencies = sorted(profile["run_metrics"].get("latencies_ms") or [])
    envelope.update(
        {
            "claims": claims,
            "evidence": evidence_rows,
            "summary": summary,
            "changes": [],
            "errors": errors,
            "operations": {
                "requests": profile["run_metrics"].get("requests", 0),
                "runtime_ms": int((time.monotonic() - company_started) * 1000),
                "third_party_cost_usd": 0,
                "bytes_received": profile["run_metrics"].get("bytes", 0),
                "latencies": {"p50_ms": latencies[len(latencies) // 2] if latencies else 0, "max_ms": latencies[-1] if latencies else 0},
            },
        }
    )
    envelope["availability"] = _availability(envelope)
    envelope["run"] = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "terminal_status": "completed" if envelope.get("state") != "failed" else "failed",
    }
    if not envelope.get("state"):
        envelope["state"] = "failed"
    return envelope


def _availability(envelope: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for claim in envelope.get("claims", []):
        state = str(claim.get("availability"))
        counts[state] = counts.get(state, 0) + 1
    return counts


def failure_envelope(organisation_number: str, run_id: str, started_at: str, message: str) -> dict[str, Any]:
    completed_at = utc_now()
    profile = minimal_profile(organisation_number)
    profile["evidence"]["registry"] = evidence("registry", "source_error", "official_registry_bulk", BULK_SOURCE, note=message)
    envelope = terminal_envelope(profile, run_id=run_id, modules=["registry"], started_at=started_at, completed_at=completed_at)
    envelope.update(
        {
            "claims": [{"field": "legal_name", "value": None, "availability": "failed", "evidence_ids": []}],
            "evidence": [],
            "summary": {"headline": "Research failed for this organisation number.", "sentences": [], "unknowns": [{"field": "legal_name", "state": "failed", "reason": message}], "method": "deterministic_template_v1"},
            "changes": [],
            "errors": [{"module": "research", "error": message}],
            "operations": {"requests": 0, "runtime_ms": 0, "third_party_cost_usd": 0},
            "availability": {"failed": 1},
        }
    )
    return envelope


def main() -> None:
    parser = argparse.ArgumentParser(description="Signalpost batch runner: one terminal envelope per input organisation number")
    parser.add_argument("--organisations", "--batch", "--input", dest="organisations", default=os.environ.get("SIGNALPOST_BATCH"))
    parser.add_argument("--bulk", default=str(ROOT / "brreg-enheter.csv"))
    parser.add_argument("--output", default="out/envelopes.jsonl")
    parser.add_argument("--profiles-output", default="out/profiles.jsonl")
    parser.add_argument("--report", default="out/run-report.json")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--expected-count", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--budget-seconds", type=float, default=120.0)
    parser.add_argument("--previous", default=None, help="previous profiles JSONL used for refresh diffs")
    parser.add_argument("--with-history", action="store_true", help="fetch the rate-limited annual-account PDF index")
    parser.add_argument("--skip-wikidata", action="store_true")
    parser.add_argument("--ui", default="out/profiles.html", help="static profile viewer output path")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    run_id = args.run_id or "run-%s" % utc_now().replace(":", "").replace("-", "")[:15]
    inputs = read_batch(args.organisations)
    orgs = [row["organisation_number"] for row in inputs]
    if args.expected_count and len(orgs) != args.expected_count:
        log("WARNING: --expected-count %d but the batch holds %d rows; scoring the batch as supplied" % (args.expected_count, len(orgs)))
    log("Batch loaded: %d organisation numbers" % len(orgs))

    bulk_path = Path(args.bulk)
    bulk_rows, bulk_meta = load_bulk(bulk_path, set(orgs))
    snapshot_sha256 = None
    if bulk_path.exists():
        import hashlib

        hasher = hashlib.sha256()
        with bulk_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
        snapshot_sha256 = hasher.hexdigest()
        bulk_meta["sha256"] = snapshot_sha256
    log("Registry snapshot: %s" % json.dumps(bulk_meta))

    wikidata_records: dict[str, dict[str, Any]] = {}
    wikidata_evidence: dict[str, Any] | None = None
    if not args.skip_wikidata:
        try:
            wikidata_records, rows, _metrics = lookup_organisations(orgs)
            wikidata_evidence = rows[0] if rows else None
            log("Wikidata: %d of %d organisations matched by organisation number" % (len(wikidata_records), len(orgs)))
        except Exception as exc:
            log("WARNING: wikidata lookup failed: %s" % exc)

    previous_profiles: dict[str, list[dict[str, Any]]] = {}
    if args.previous and Path(args.previous).exists():
        for line in Path(args.previous).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                previous_profiles[row.get("organisation_number")] = row.get("claims", [])
        log("Previous snapshot loaded: %d profiles" % len(previous_profiles))

    started_at = utc_now()
    wall_start = time.monotonic()
    envelopes: dict[str, dict[str, Any]] = {}
    resumed = 0
    profiles_output = Path(args.profiles_output)
    if args.resume and profiles_output.exists():
        prior = {row.get("organisation_number"): row for row in (json.loads(line) for line in profiles_output.read_text(encoding="utf-8").splitlines() if line.strip())}
        for org in orgs:
            if org in prior and org not in envelopes:
                envelopes[org] = prior[org]
        resumed = len(envelopes)
        if resumed:
            log("Resumed %d envelopes from %s" % (resumed, profiles_output))

    pending = [org for org in orgs if org not in envelopes]
    annotations = {row["organisation_number"]: row for row in inputs}
    raw_rows = {org: bulk_rows.get(org) for org in bulk_rows} if bulk_rows else {}

    def job(organisation_number: str) -> dict[str, Any]:
        raw = raw_rows.get(organisation_number)
        try:
            return research_company(
                organisation_number,
                raw,
                wikidata_records.get(organisation_number),
                wikidata_evidence,
                run_id=run_id,
                started_at=started_at,
                budget_seconds=args.budget_seconds,
                with_history=args.with_history,
                snapshot_sha256=snapshot_sha256,
            )
        except Exception as exc:
            message = "%s: %s" % (type(exc).__name__, str(exc)[:300])
            log("FAILURE %s: %s" % (organisation_number, message))
            return failure_envelope(organisation_number, run_id, started_at, message)

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(job, org): org for org in pending}
            done_count = 0
            for future in as_completed(futures):
                org = futures[future]
                try:
                    envelope = future.result(timeout=args.budget_seconds + 30)
                except Exception as exc:
                    envelope = failure_envelope(org, run_id, started_at, "worker failure: %s" % exc)
                if envelope.get("organisation_number") != org:
                    envelope = failure_envelope(org, run_id, started_at, "envelope organisation mismatch")
                envelopes[org] = envelope
                done_count += 1
                if done_count % 25 == 0 or done_count == len(pending):
                    write_jsonl(profiles_output, [envelopes[org] for org in orgs if org in envelopes])
                    log("Progress: %d/%d" % (done_count, len(pending)))

    ordered = [envelopes.get(org) or failure_envelope(org, run_id, started_at, "no result produced for this input") for org in orgs]

    for envelope in ordered:
        org = envelope.get("organisation_number")
        if org in previous_profiles and previous_profiles[org]:
            envelope["changes"] = diff_claims(previous_profiles[org], envelope.get("claims") or [])

    write_jsonl(Path(args.output), ordered)
    write_jsonl(profiles_output, ordered)

    latencies = sorted(e.get("operations", {}).get("runtime_ms", 0) for e in ordered)
    requests_total = sum(int(e.get("operations", {}).get("requests", 0)) for e in ordered)
    states: dict[str, int] = {}
    module_states: dict[str, int] = {}
    for envelope in ordered:
        states[str(envelope.get("state"))] = states.get(str(envelope.get("state")), 0) + 1
        for module, detail in (envelope.get("modules") or {}).items():
            module_states[str(detail.get("state"))] = module_states.get(str(detail.get("state")), 0) + 1
    duplicate_count = len(ordered) - len({e.get("organisation_number") for e in ordered})
    report = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": utc_now(),
        "wall_seconds": round(time.monotonic() - wall_start, 2),
        "input_count": len(orgs),
        "emitted_envelopes": len(ordered),
        "validation": {
            "passed": len(ordered) == len(orgs) and duplicate_count == 0,
            "checks": {
                "one_envelope_per_input": len(ordered) == len(orgs),
                "unique_organisation_numbers": duplicate_count == 0,
                "no_missing_rows": all(e.get("organisation_number") for e in ordered),
            },
        },
        "state_counts": states,
        "module_state_counts": module_states,
        "claim_states": _claim_states(ordered),
        "operations": {
            "requests": requests_total,
            "third_party_cost_usd": 0,
            "p50_ms": latencies[len(latencies) // 2] if latencies else 0,
            "p95_ms": latencies[int(len(latencies) * 0.95)] if latencies else 0,
            "max_ms": latencies[-1] if latencies else 0,
            "resumed": resumed,
        },
        "precision": _precision(ordered),
        "sources": ["brreg_enhetsregisteret", "brreg_regnskapsregisteret", "company_owned_sites", "wikidata_cc0"],
        "models": "none (deterministic extraction and templating)",
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log("Emitted %d envelopes, %d requests, cost $%.2f" % (len(ordered), requests_total, 0.0))
    log("Report: %s" % args.report)

    if args.ui:
        try:
            from build_ui import build_viewer

            build_viewer([json.loads(json.dumps(e)) for e in ordered], Path(args.ui))
            log("Viewer: %s" % args.ui)
        except Exception as exc:
            log("WARNING: viewer build failed: %s" % exc)

    if not report["validation"]["passed"]:
        raise SystemExit("Validation failed: %s" % json.dumps(report["validation"]["checks"]))


def _precision(envelopes: list[dict[str, Any]]) -> dict[str, Any]:
    """Evidence hygiene: how much of what we publish can actually be traced back to a response."""
    claims = [claim for envelope in envelopes for claim in envelope.get("claims", [])]
    rows = [row for envelope in envelopes for row in envelope.get("evidence", [])]
    available = [claim for claim in claims if claim.get("availability") == "available"]
    with_evidence = [claim for claim in available if claim.get("evidence_ids")]
    row_ids = {row.get("id") for row in rows}
    resolvable = [claim for claim in with_evidence if all(eid in row_ids for eid in claim.get("evidence_ids", []))]
    with_url = [row for row in rows if row.get("source_url")]
    with_hash = [row for row in rows if row.get("content_sha256")]
    with_time = [row for row in rows if row.get("retrieved_at")]
    denominator = max(len(available), 1)
    row_denominator = max(len(rows), 1)
    return {
        "available_claims": len(available),
        "available_claims_with_evidence_ids": len(with_evidence),
        "available_claims_with_resolvable_evidence": len(resolvable),
        "share_available_claims_cited": round(len(with_evidence) / denominator, 4),
        "share_available_claims_resolvable": round(len(resolvable) / denominator, 4),
        "evidence_rows": len(rows),
        "share_evidence_rows_with_url": round(len(with_url) / row_denominator, 4),
        "share_evidence_rows_with_content_sha256": round(len(with_hash) / row_denominator, 4),
        "share_evidence_rows_with_retrieval_time": round(len(with_time) / row_denominator, 4),
    }


def _claim_states(envelopes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for envelope in envelopes:
        for claim in envelope.get("claims", []):
            state = str(claim.get("availability"))
            counts[state] = counts.get(state, 0) + 1
    return counts


if __name__ == "__main__":
    main()
