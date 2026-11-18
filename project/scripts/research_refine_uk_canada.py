#!/usr/bin/env python3
"""Freeze UK/Canada evidence refinements from archived official originals.

Offline only. Writes exclusively data/research/evidence_refinement/uk_canada.
It does not modify the shared models or the application dataset.
Run: .research-venv/bin/python scripts/research_refine_uk_canada.py
"""
from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/evidence_refinement/uk_canada"
OUT = ROOT / "data/research/evidence_refinement/uk_canada"
RETRIEVED = "2026-11-16"

# Table row IDs are stable, human-readable locators in the frozen originals.
# The six selected fee lines are disjoint fee components. Other rows reconcile
# their programme total or document exclusions; they must not join core flows.
LINES = {
    "employer_compliance": (12, "Employer Compliance Fee", "excluded_employer_charge"),
    "open_work": (13, "Open work permit - Exempt foreign workers", "selected_core_fee"),
    "iec_nonrespendable": (23, "Non-respendable revenues", "excluded_iec_participation_fee"),
    "iec_respendable": (24, "Respendable revenues", "excluded_iec_participation_fee"),
    "trv_multiple": (32, "Multiple entry", "selected_core_fee"),
    "trv_family": (33, "Maximum per family", "selected_core_fee"),
    "work": (35, "Work permit", "selected_core_fee"),
    "work_artists": (36, "Group of artists", "selected_core_fee"),
    "study": (37, "Study permit", "selected_core_fee"),
    "temporary_resident_permit": (39, "Temporary resident permit", "excluded_distinct_admissibility_permit"),
    "restoration": (40, "Restoration of temporary residence status", "excluded_status_restoration"),
    "biometrics": (46, "Biometric", "excluded_separate_biometric_fee"),
    "eta": (47, "Electronic Travel Authorization (eTA)", "excluded_eta"),
    "deferred_regulatory": (49, "Deferred revenues", "excluded_deferred_account"),
}
CORE = [k for k, (_, _, scope) in LINES.items() if scope == "selected_core_fee"]
PROGRAMME = [k for k in LINES if k not in ("biometrics", "deferred_regulatory")]
PA_TABLE_PAGE = {2025: 313, 2026: 319}


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source_records():
    result = []
    for year in (2025, 2026):
        for suffix, extension, url in [
            ("revenues", "html", f"https://www.tpsgc-pwgsc.gc.ca/recgen/cpc-pac/{year}/vol2/ircc/rev-eng.html"),
            ("intro", "html", f"https://www.tpsgc-pwgsc.gc.ca/recgen/cpc-pac/{year}/vol2/intro-eng.html"),
            ("volume2", "pdf", f"https://www.tpsgc-pwgsc.gc.ca/recgen/cpc-pac/{year}/pdf/{year}-vol2-eng.pdf"),
        ]:
            stem = f"ca_public_accounts_{year}"
            filename = f"{stem}.html" if suffix == "revenues" else f"{stem}_{suffix}.{extension}"
            path = RAW / filename
            data = path.read_bytes()
            result.append({
                "source_id": f"{stem}_{suffix}", "url": url,
                "agency": "Receiver General for Canada / Public Services and Procurement Canada",
                "title": f"Public Accounts of Canada {year}, Volume II: {suffix}",
                "retrieved_at": RETRIEVED, "local_path": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "source_quality": "official_primary",
                "data_version": f"Fiscal year {year - 1}-04-01 to {year}-03-31; comparative prior year",
                "format_priority": "The official introduction states that the PDF prevails if PDF and HTML differ.",
            })
    return result


def financial_observations():
    observations = {}
    pdf_checks = []
    for year in (2025, 2026):
        soup = BeautifulSoup((RAW / f"ca_public_accounts_{year}.html").read_text(), "html.parser")
        table = soup.select_one("table")
        assert "in dollars" in table.caption.get_text(" ", strip=True)
        assert [x.get_text(" ", strip=True) for x in table.select("thead th")] == ["Description", "Current year", "Previous year"]
        reader = PdfReader(RAW / f"ca_public_accounts_{year}_volume2.pdf")
        first_page = PA_TABLE_PAGE[year]
        pages = [{"pdf_page": n, "text": reader.pages[n - 1].extract_text() or ""}
                 for n in (3, first_page, first_page + 1)]
        dump(f"ca_public_accounts_{year}_pdf_excerpts.json", pages)
        assert f"{year - 1}–{year}" in pages[0]["text"]
        table_text = " ".join(x["text"] for x in pages[1:])
        for component, (row_number, label, scope) in LINES.items():
            cell = table.select_one(f'th[id$="_r{row_number}"]')
            assert cell.get_text(" ", strip=True) == label
            values = [int(x.get_text(" ", strip=True).replace(",", "")) for x in cell.parent.select("td")]
            assert len(values) == 2
            for index, value in enumerate(values):
                fiscal_end = year - index
                key = (fiscal_end, component)
                sid = f"ca_public_accounts_{year}_revenues"
                locator = f'table#{table["id"]}, th#{cell["id"]}; column {"Current year" if index == 0 else "Previous year"}'
                evidence = {"source_id": sid, "locator": locator,
                            "pdf_source_id": f"ca_public_accounts_{year}_volume2",
                            "pdf_locator": f"PDF pages {first_page}-{first_page + 1}, Revenues (in dollars), {label}"}
                # PDF text extraction preserves the row order and both columns.
                # Matching the label and the adjacent pair catches swapped columns.
                # Duplicate labels (work permit/deferred revenues) are disambiguated
                # by the pair of fiscal amounts and the HTML's stable row ID.
                pattern = re.escape(label) + r"[\s.]+" + re.escape(f"{values[0]:,}") + r"\s+" + re.escape(f"{values[1]:,}")
                matched_pdf = bool(re.search(pattern, table_text))
                pdf_checks.append({"component": component, "publication": year, "column": index,
                                   "value": value, "matches_pdf_label_and_pair": matched_pdf})
                assert matched_pdf, (year, component, pattern)
                if key in observations:
                    assert observations[key]["value"] == value, ("Comparative year mismatch", key)
                    observations[key]["supporting_evidence"].append(evidence)
                    continue
                group = "Temporary resident visa" if component.startswith("trv_") else "Work permit" if component in ("work", "work_artists") else "International Experience Canada" if component.startswith("iec_") else "Rights and privileges" if component in ("open_work", "employer_compliance") else "Services of a regulatory nature"
                observations[key] = {
                    "observation_id": f"ca_pa_{component}_fy{fiscal_end - 1}_{fiscal_end}",
                    "destination": "CAN", "origin_name": "WORLD", "component": component,
                    "metric": group + " / " + label + " revenue", "value": value, "unit": "CAD",
                    "period_start": f"{fiscal_end - 1}-04-01", "period_end": f"{fiscal_end}-03-31",
                    "period_type": "fiscal_year", "source_id": sid, "source_ids": [sid], "locator": locator,
                    "source_quality": "official_primary", "calculation_kind": "observed",
                    "scope_in_model": scope, "supporting_evidence": [evidence],
                    "scope": "Published government fee revenue account; not a measured calendar-year bilateral payment. Country allocation absent. Study/work include inland processing and extensions.",
                    "accounting_basis": "Reported fiscal revenue line; not independently established to be cash received. Do not add deferred revenue accounts, programme totals or remissions.",
                }
    result = list(sorted(observations.values(), key=lambda x: (x["period_start"], x["component"])))
    for r in result:
        r["source_ids"] = sorted({e["source_id"] for e in r["supporting_evidence"]})
    assert len(result) == 3 * len(LINES)
    return result, pdf_checks


def reconciliation(rows):
    values = {(r["period_start"], r["component"]): r["value"] for r in rows}
    original = json.loads((ROOT / "data/research/uk_canada/financial_observations.json").read_text())
    checks = []
    for start in ("2024-04-01", "2025-04-01"):
        programme = next(x for x in original if x["destination"] == "CAN" and x["period_start"] == start and x["metric"] == "Temporary Residence Program Fees revenue")
        parts = {k: values[start, k] for k in PROGRAMME}
        checks.append({"check": "Temporary Residence fee programme reconciles exactly to Public Accounts leaf accounts",
                       "period_start": start, "actual_programme": programme["value"],
                       "sum_components": sum(parts.values()), "components": parts,
                       "programme_source_id": programme["source_id"], "programme_locator": programme["locator"],
                       "passed": sum(parts.values()) == programme["value"],
                       "interpretation": "Reconciliation only. Programme grouping and component leaves are alternative views of the same income, never additive."})
    mapping = {
        "trv_family": "Temporary Resident visa - maximum fee for family revenue",
        "study": "Study Permit revenue", "work": "Work Permit revenue",
        "work_artists": "Work Permit - maximum fee for group of three or more performing artists and their staff revenue",
        "open_work": "Open Work Permit Holder revenue", "eta": "Electronic Travel Authorizations (eTA) revenue",
    }
    for component, metric in mapping.items():
        old = next(x for x in original if x["destination"] == "CAN" and x["period_start"] == "2024-04-01" and x["metric"] == metric)
        checks.append({"check": "Public Accounts FY2024-25 leaf equals existing Fees Report observation",
                       "component": component, "old_observation_id": old["observation_id"],
                       "old_value": old["value"], "new_value": values["2024-04-01", component],
                       "passed": old["value"] == values["2024-04-01", component]})
    bio = sum(x["value"] for x in original if x["destination"] == "CAN" and x["period_start"] == "2024-04-01" and x["metric"].startswith("Biometric"))
    checks.append({"check": "Public Accounts biometric aggregate equals the three disjoint Fees Report biometric fees",
                   "fees_report_sum": bio, "public_accounts": values["2024-04-01", "biometrics"],
                   "passed": bio == values["2024-04-01", "biometrics"]})
    assert all(x["passed"] for x in checks)
    return checks


def uk_tariff_verification():
    # (outside-UK table, row in April2024 table, row in April2025/October2024).
    locators = {
        "visit_short": (1, 2, 2), "visit_2y": (1, 3, 3), "visit_5y": (1, 4, 4), "visit_10y": (1, 5, 5),
        "study": (3, 2, 2), "short_study": (3, 4, 4),
        "sw_short": (2, 13, 13), "sw_long": (2, 14, 14),
        "sw_salary_short": (2, 16, 15), "sw_salary_long": (2, 18, 16),
        "hc_short": (2, 19, 17), "hc_long": (2, 20, 18),
        "temporary": (2, 28, 24), "hpi": (2, 37, 33), "talent": (2, 8, 8),
        "innovator": (2, 2, 2), "startup": (2, 5, 5), "investor": (2, 12, 12),
        "family": (1, 17, 17), "adult_relative": (1, 18, 18), "refugee_relative": (1, 19, 19),
        "indefinite": (1, 20, 20), "generic": (1, 14, 14), "transit_air": (1, 8, 8),
        "transit_land": (1, 9, 9), "bno_short": (1, 15, 15), "bno_long": (1, 16, 16), "right_abode": (1, 12, 12),
    }
    tree = ast.parse((ROOT / "scripts/model_uk_canada.py").read_text())
    model_tariffs = next(ast.literal_eval(x.value) for x in tree.body if isinstance(x, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TARIFF" for t in x.targets))
    soups = {sid: BeautifulSoup((ROOT / f"data/raw/uk/{sid}.html").read_text(), "html.parser")
             for sid in ("uk_fees_apr2024", "uk_fees_oct2024", "uk_fees_apr2025")}
    def fee_row(sid, table, row):
        tr = soups[sid].select("table")[table - 1].select("tr")[row - 1]
        cells = [x.get_text(" ", strip=True) for x in tr.select("th,td")]
        return {"source_id": sid, "locator": f"HTML table {table}, row {row}, outside-UK fees",
                "label": cells[0], "before": int(cells[1].replace("£", "").replace(",", "")),
                "after": int(cells[2].replace("£", "").replace(",", ""))}
    result = []
    for key, (table, row_2024, row_2025) in locators.items():
        a = fee_row("uk_fees_apr2024", table, row_2024)
        b = fee_row("uk_fees_apr2025", table, row_2025)
        c = fee_row("uk_fees_oct2024", table, row_2025)
        vector = [a["before"], a["after"], b["after"]]
        result.append({"tariff_key": key, "model_vector": list(model_tariffs[key]), "original_vector": vector,
                       "original_rows": [a, c, b],
                       "matches": vector == list(model_tariffs[key]) and c["after"] == a["after"] == b["before"]})
    assert set(locators) == set(model_tariffs) - {"zero"}
    assert all(x["matches"] for x in result)
    return {"positive_tariff_count": len(result), "all_positive_tariffs_match": True, "rows": result,
            "zero_tariffs": "Not verified by a zero-fee row in these tariff tables. Existing policy exemptions remain explicitly marked classifications/assumptions.",
            "remaining_uncertainty": "Duration mixtures, salary-list shares, fee waivers, China two-year residence eligibility and legacy-route mapping remain assumptions; checking published price vectors does not validate their shares.",
            "account_scope": "The model uses overseas nationality-by-quarter application leaves. It does not calibrate overseas flows to broad Visa and immigration income. IHS, ETA, premium services, employer fees and private services remain excluded."}


def recommended_bridge(rows):
    by_key = {(int(r["period_start"][:4]), r["component"]): r for r in rows}
    result = []
    for year in (2024, 2025):
        for component in CORE:
            prev, current = by_key[year - 1, component], by_key[year, component]
            result.append({
                "component": component, "year": year, "currency": "CAD",
                "amount": .25 * prev["value"] + .75 * current["value"],
                "lower": min(.15 * prev["value"] + .85 * current["value"], .35 * prev["value"] + .65 * current["value"]),
                "upper": max(.15 * prev["value"] + .85 * current["value"], .35 * prev["value"] + .65 * current["value"]),
                "observation_ids": [prev["observation_id"], current["observation_id"]],
                "source_ids": sorted(set(prev["source_ids"] + current["source_ids"])),
                "formula": ".25 * revenue_FY_ending_in_calendar_year + .75 * revenue_FY_starting_in_calendar_year",
                "classification": "calendar_model_from_fiscal_revenue; not observed calendar revenue",
                "assumption": "Uniform revenue recognition within each source fiscal year. The first quarter is from the preceding FY, the last three quarters from the next FY.",
                "sensitivity": "Common calendar interpolation weight w=0.15/0.25/0.35 on preceding fiscal revenue, complementary 1-w=0.85/0.75/0.65 on current fiscal revenue. Selected timing sensitivity, not empirical confidence limits. Use common weights across components for national totals.",
            })
    return result


def replacement_map(rows):
    old_models = {
        "trv_family": "ca_family_revenue_bridge_v1", "study": "ca_study_revenue_bridge_v1",
        "work": "ca_work_revenue_bridge_v1", "work_artists": "ca_work_group_revenue_bridge_v1",
        "open_work": "ca_open_work_revenue_bridge_v1",
        "trv_multiple": ["ca_trv_single_2024_v1", "ca_trv_single_2025_v1", "ca_trv_individual_tariff_scenario_v1"],
    }
    return [{"component": k, "old_method_ids": v if isinstance(v, list) else [v],
             "replacement_method_id_suggestion": f"ca_pa_{k}_calendar_bridge_v2",
             "actual_observation_ids": [r["observation_id"] for r in rows if r["component"] == k],
             "remove_old_flows": True, "add_on_top_of_old_flows": False,
             "country_allocation": "Visitor V-1 approved-country proxy" if k.startswith("trv_") else "New study permit processed-country proxy, although revenue includes extensions" if k == "study" else "UNK; do not fabricate nationalities from visitor or study shares",
             "notes": "Use actual labelled Multiple entry account. Do not infer an unreported single-entry residual or subtract family equivalent persons; family is already a separate revenue account." if k == "trv_multiple" else "Distinct actual fiscal fee account; only calendar timing and payer-country allocation are modelled."}
            for k, v in old_models.items()]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = source_records()
    rows, pdf_checks = financial_observations()
    reconciliations = reconciliation(rows)
    uk = uk_tariff_verification()
    bridge = recommended_bridge(rows)
    dump("sources.json", sources)
    dump("observations.json", rows)
    with (OUT / "observations.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in r.items()})
    dump("reconciliation.json", reconciliations)
    dump("uk_tariff_verification.json", uk)
    dump("calendar_bridge_recommendation.json", bridge)
    dump("replacement_map.json", replacement_map(rows))
    result = {"passed": True, "source_count": len(sources), "observation_count": len(rows),
              "fiscal_periods": ["2023-04-01/2024-03-31", "2024-04-01/2025-03-31", "2025-04-01/2026-03-31"],
              "fiscal_core_totals_CAD": {str(y): sum(r["value"] for r in rows if r["period_start"] == f"{y}-04-01" and r["component"] in CORE) for y in (2023, 2024, 2025)},
              "recommended_calendar_core_totals_CAD": {str(y): sum(r["amount"] for r in bridge if r["year"] == y) for y in (2024, 2025)},
              "unique_observation_ids": len({r["observation_id"] for r in rows}) == len(rows),
              "pdf_row_column_checks": pdf_checks,
              "programme_reconciliations": reconciliations[:2],
              "uk_positive_tariffs_match": uk["all_positive_tariffs_match"],
              "shared_models_modified": False}
    dump("checks.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("pdf_row_column_checks", "programme_reconciliations")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
