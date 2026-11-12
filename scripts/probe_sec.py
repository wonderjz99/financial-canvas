#!/usr/bin/env python3
"""Read-only SEC coverage probe; cached analysis is the default operation.

Issuer profiles select the research samples; this is not a production financial adapter.
Only --fetch performs network requests. No third-party packages are required.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from financial_visualizer.issuers import default_symbols, get_issuer, load_registry
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A"}
MAPPING_VERSION = "sec-two-issuer-probe-1"
EXPENSE_COMPONENT_TAGS = {
    "research_development": ["ResearchAndDevelopmentExpense"],
    "selling_general_admin": ["SellingGeneralAndAdministrativeExpense"],
    "sales_marketing": ["SellingAndMarketingExpense"],
    "general_admin": ["GeneralAndAdministrativeExpense"],
}
METRICS = {
    "revenue": ("duration", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]),
    "cost_of_revenue": ("duration", ["CostOfRevenue", "CostOfGoodsAndServicesSold"]),
    "gross_profit": ("duration", ["GrossProfit"]),
    "operating_expenses": ("duration", ["OperatingExpenses"]),
    "operating_income": ("duration", ["OperatingIncomeLoss"]),
    "pretax_income": ("duration", ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"]),
    "pretax_before_equity_method": ("duration", ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"]),
    "income_tax": ("duration", ["IncomeTaxExpenseBenefit"]),
    "net_income": ("duration", ["NetIncomeLoss"]),
    "profit_loss_total": ("duration", ["ProfitLoss"]),
    "operating_cash": ("duration", ["NetCashProvidedByUsedInOperatingActivities"]),
    "investing_cash": ("duration", ["NetCashProvidedByUsedInInvestingActivities"]),
    "financing_cash": ("duration", ["NetCashProvidedByUsedInFinancingActivities"]),
    "cash_change_including_fx": ("duration", ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"]),
    "cash_fx": ("duration", ["EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations", "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    "depreciation_amortization": ("duration", ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"]),
    "depreciation_only": ("duration", ["Depreciation"]),
    "stock_based_compensation": ("duration", ["ShareBasedCompensation"]),
    "deferred_income_tax": ("duration", ["DeferredIncomeTaxExpenseBenefit"]),
    "purchases_ppe": ("duration", ["PaymentsToAcquirePropertyPlantAndEquipment"]),
    "purchases_productive_assets": ("duration", ["PaymentsToAcquireProductiveAssets"]),
    "cash_dividends": ("duration", ["PaymentsOfDividends"]),
    "cash_share_repurchases": ("duration", ["PaymentsForRepurchaseOfCommonStock"]),
    "assets": ("instant", ["Assets"]),
    "liabilities": ("instant", ["Liabilities"]),
    "equity_parent": ("instant", ["StockholdersEquity"]),
    "equity_including_nci": ("instant", ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
    "noncontrolling_interest": ("instant", ["MinorityInterest"]),
    "cash_and_equivalents": ("instant", ["CashAndCashEquivalentsAtCarryingValue"]),
    "cash_including_restricted": ("instant", ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    "ppe_net": ("instant", ["PropertyPlantAndEquipmentNet"]),
    "operating_lease_rou_asset": ("instant", ["OperatingLeaseRightOfUseAsset"]),
    "receivables_net": ("instant", ["AccountsReceivableNetCurrent"]),
    "inventory": ("instant", ["InventoryNet"]),
    "accounts_payable": ("instant", ["AccountsPayableCurrent"]),
}


def decimal_string(value):
    return format(Decimal(value), "f")


def load_json(path):
    return json.loads(path.read_text(), parse_float=Decimal)


def save_json(path, value):
    def encode(item):
        if isinstance(item, Decimal):
            return decimal_string(item)
        raise TypeError(f"Unsupported serialization type: {type(item).__name__}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=encode) + "\n")


def fetch_inputs(directory, as_of, user_agent, registry=None, symbols=None):
    """Make at most one request per endpoint; existing successful snapshots stay intact."""
    for symbol in symbols or default_symbols(registry):
        issuer = get_issuer(symbol, registry)
        cik = issuer["cik"]
        paths = {"submissions": f"/submissions/CIK{cik}.json",
                 "companyfacts": f"/api/xbrl/companyfacts/CIK{cik}.json"}
        for kind, path in paths.items():
            target = directory / f"{symbol}-{kind}.json"
            meta_path = directory / f"{symbol}-{kind}.meta.json"
            if target.exists() and meta_path.exists():
                print(f"Using existing snapshot: {target.name}")
                continue
            meta = {"url": "https://data.sec.gov" + path, "as_of": as_of,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "transport": "urllib", "user_agent": user_agent}
            try:
                request = urllib.request.Request(meta["url"], headers={
                    "User-Agent": user_agent, "Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=25) as response:
                    body = response.read()
                    meta.update(status=response.status, content_type=response.headers.get("Content-Type"),
                                response_date=response.headers.get("Date"), bytes=len(body),
                                sha256=hashlib.sha256(body).hexdigest())
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body)
            except urllib.error.HTTPError as error:
                body = error.read()
                meta.update(status=error.code, error="HTTPError", bytes=len(body),
                            sha256=hashlib.sha256(body).hexdigest())
                target.with_suffix(".error.html").write_bytes(body)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                meta.update(status=None, error=type(error).__name__, message=str(error))
            save_json(meta_path, meta)
            print(f"{symbol} {kind}: {meta.get('status')} {meta.get('error', '')}")
            time.sleep(1.1)


def recent_annuals(submissions, as_of):
    """Read recent submissions only; report a gap instead of inventing older filings."""
    recent = submissions["filings"]["recent"]
    results = []
    for index, form in enumerate(recent["form"]):
        row = {key: values[index] for key, values in recent.items()
               if isinstance(values, list) and index < len(values)}
        if form in ANNUAL_FORMS and row.get("filingDate", "9999") <= as_of and row.get("reportDate"):
            results.append(row)
    return sorted(results, key=lambda row: (row["reportDate"], row["filingDate"], row["accessionNumber"]), reverse=True)


def fact_url(cik, accession):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"


def eligible_fact(value, end, start, as_of):
    if value.get("form") not in ANNUAL_FORMS or value.get("filed", "9999") > as_of:
        return False
    if value.get("end") != end or value.get("val") is None:
        return False
    if start is None:
        return not value.get("start")
    return value.get("start") == start


def select_fact(facts, tags, currency, end, start, as_of, cik):
    """Select latest available annual disclosure; conflicting latest values remain unknown."""
    candidates = []
    for priority, tag in enumerate(tags):
        for raw in facts.get(tag, {}).get("units", {}).get(currency, []):
            if eligible_fact(raw, end, start, as_of):
                candidates.append((raw.get("filed", ""), priority, tag, raw))
    if not candidates:
        return {"status": "missing", "valueDecimal": None, "candidate_tags": tags,
                "unit": currency, "start": start, "end": end, "versions": []}
    candidates.sort(key=lambda item: (item[0], -item[1], item[3].get("accn", "")), reverse=True)
    latest_date = candidates[0][0]
    latest = [item for item in candidates if item[0] == latest_date]
    latest_values = {decimal_string(item[3]["val"]) for item in latest}
    versions = []
    seen = set()
    for _, _, tag, raw in candidates:
        identity = (tag, raw.get("accn"), raw.get("filed"), decimal_string(raw["val"]))
        if identity in seen:
            continue
        seen.add(identity)
        versions.append({"tag": tag, "valueDecimal": decimal_string(raw["val"]),
                         **{key: raw.get(key) for key in ["accn", "filed", "form", "fy", "fp", "frame"]}})
    if len(latest_values) != 1:
        return {"status": "ambiguous_latest_values", "valueDecimal": None,
                "unit": currency, "start": start, "end": end, "versions": versions}
    _, _, tag, raw = latest[0]
    fingerprint = "|".join([str(cik), tag, currency, start or "", end, raw["accn"], decimal_string(raw["val"])])
    return {"status": "available", "factId": "sec-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:24],
            "namespace": "us-gaap", "tag": tag, "label": facts[tag].get("label"),
            "valueDecimal": decimal_string(raw["val"]), "unit": currency, "start": start, "end": end,
            "source_url": fact_url(cik, raw["accn"]), "entity_scope": "entire_filing_entity",
            "accession": raw["accn"], "filed": raw.get("filed"), "form": raw.get("form"),
            "source_fy": raw.get("fy"), "source_fp": raw.get("fp"),
            "version_values_changed": len({item["valueDecimal"] for item in versions}) > 1,
            "selection_rule": "latest annual disclosure by filed date, exact unit/start/end; conflicting latest values block selection",
            "versions": versions}


def annual_periods(submissions, facts, currency, as_of):
    """Use annual report dates plus corroborating annual revenue durations, never fp alone."""
    filings = recent_annuals(submissions, as_of)
    by_end = {}
    for row in filings:
        by_end.setdefault(row["reportDate"], row)
    ends = sorted(by_end, reverse=True)[:6]
    periods = []
    for index, end in enumerate(ends[:5]):
        expected_start = (date.fromisoformat(ends[index + 1]) + timedelta(days=1)).isoformat() if index + 1 < len(ends) else None
        starts = set()
        for tag in METRICS["revenue"][1]:
            for raw in facts.get(tag, {}).get("units", {}).get(currency, []):
                start = raw.get("start")
                if start and eligible_fact(raw, end, start, as_of):
                    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
                    if 330 <= days <= 380:
                        starts.add(start)
        start = expected_start if expected_start in starts else next(iter(starts)) if len(starts) == 1 else None
        periods.append({"fiscal_year": int(by_end[end]["reportDate"][:4]), "start": start, "end": end,
                        "annual_revenue_start_candidates": sorted(starts),
                        "matches_previous_annual_balance_date": start == expected_start and start is not None,
                        "anchor_filing": by_end[end]})
    return periods, ends, filings


def amount(items, key):
    value = items.get(key, {}).get("valueDecimal")
    return Decimal(value) if value is not None else None


def equality_check(name, left, right, inputs, note=None):
    complete = left is not None and right is not None
    return {"name": name, "status": ("pass" if left == right else "fail") if complete else "blocked_missing_input",
            "leftDecimal": decimal_string(left) if left is not None else None,
            "rightDecimal": decimal_string(right) if right is not None else None,
            "differenceDecimal": decimal_string(left - right) if complete else None,
            "inputs": inputs, "note": note}


def sum_if_known(values):
    return sum(values, Decimal(0)) if all(value is not None for value in values) else None


def balance_identity(ending):
    liabilities, equity = amount(ending, "liabilities"), amount(ending, "equity_including_nci")
    equity_basis = "equity_including_nci"
    if equity is None:
        equity, minority = amount(ending, "equity_parent"), amount(ending, "noncontrolling_interest")
        if minority is not None and equity is not None:
            equity += minority
            equity_basis = "equity_parent + noncontrolling_interest"
        else:
            equity_basis = "equity_parent; NCI input absent, arithmetic identity only"
    return equality_check("assets_equals_liabilities_plus_equity", amount(ending, "assets"),
                          sum_if_known([liabilities, equity]), ["assets", "liabilities", equity_basis])


def checks_for_period(flow, ending, beginning):
    result = []
    revenue, cost, gross = [amount(flow, key) for key in ["revenue", "cost_of_revenue", "gross_profit"]]
    if gross is None and revenue is not None and cost is not None:
        gross = revenue - cost
        fingerprint = "|".join([flow["revenue"]["factId"], flow["cost_of_revenue"]["factId"], MAPPING_VERSION])
        flow["gross_profit_derived"] = {"status": "derived", "valueDecimal": decimal_string(gross),
                                        "factId": "derived-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:24],
                                        "unit": flow["revenue"]["unit"], "start": flow["revenue"]["start"], "end": flow["revenue"]["end"],
                                        "method_version": MAPPING_VERSION, "formula": "revenue - cost_of_revenue",
                                        "inputs": [flow["revenue"]["factId"], flow["cost_of_revenue"]["factId"]]}
    result.append(equality_check("revenue_minus_cost_equals_disclosed_gross_profit", revenue - cost if revenue is not None and cost is not None else None,
                                 amount(flow, "gross_profit"), ["revenue", "cost_of_revenue", "gross_profit"], "A derived gross profit is not an independent third input."))
    expenses = amount(flow, "operating_expenses")
    result.append(equality_check("gross_profit_minus_opex_equals_operating_income", gross - expenses if gross is not None and expenses is not None else None,
                                 amount(flow, "operating_income"), ["gross_profit (reported or derived)", "operating_expenses", "operating_income"]))
    pretax, tax = amount(flow, "pretax_income"), amount(flow, "income_tax")
    result.append(equality_check("pretax_minus_tax_equals_net_income", pretax - tax if pretax is not None and tax is not None else None,
                                 amount(flow, "net_income"), ["pretax_income", "income_tax", "net_income"]))
    result.append(balance_identity(ending))
    cash_end, cash_begin = amount(ending, "cash_including_restricted"), amount(beginning, "cash_including_restricted")
    change = amount(flow, "cash_change_including_fx")
    result.append(equality_check("cash_scope_balance_change_equals_disclosed_cash_change", cash_end - cash_begin if cash_end is not None and cash_begin is not None else None,
                                 change, ["cash_including_restricted ending", "cash_including_restricted beginning", "cash_change_including_fx"]))
    activities = [amount(flow, key) for key in ["operating_cash", "investing_cash", "financing_cash"]]
    fx = amount(flow, "cash_fx")
    result.append(equality_check("cash_activities_plus_disclosed_fx_equals_cash_change", sum_if_known([*activities, fx]), change,
                                 ["operating_cash", "investing_cash", "financing_cash", "cash_fx", "cash_change_including_fx"],
                                 "Missing FX is unknown, never zero-filled."))
    result.append(equality_check("cash_activity_subtotal_equals_disclosed_cash_change", sum_if_known(activities), change,
                                 ["operating_cash", "investing_cash", "financing_cash", "cash_change_including_fx"],
                                 "A difference can be explained by FX/other scope changes; this is a subtotal diagnostic, not a financial correctness verdict."))
    result[-1]["kind"] = "subtotal_diagnostic"
    if result[-1]["status"] == "fail":
        result[-1]["status"] = "diagnostic_difference"
    return result


def analyze_issuer(symbol, directory, as_of, registry=None):
    issuer = get_issuer(symbol, registry)
    submissions_path, facts_path = [directory / f"{symbol}-{kind}.json" for kind in ["submissions", "companyfacts"]]
    if not submissions_path.exists() or not facts_path.exists():
        return {"symbol": symbol, "status": "acquisition_incomplete", "checks": [], "periods": []}
    for kind, path in [("submissions", submissions_path), ("companyfacts", facts_path)]:
        meta_path = directory / f"{symbol}-{kind}.meta.json"
        if not meta_path.exists() or load_json(meta_path).get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            return {"symbol": symbol, "status": "evidence_integrity_failure", "periods": [], "checks": []}
    submissions, companyfacts = load_json(submissions_path), load_json(facts_path)
    identity_ok = int(submissions["cik"]) == int(issuer["cik"]) == int(companyfacts["cik"]) and symbol in submissions.get("tickers", [])
    if not identity_ok:
        return {"symbol": symbol, "status": "identity_mismatch", "periods": [], "checks": []}
    facts, currency = companyfacts["facts"]["us-gaap"], issuer["currency"]
    periods, ends, filings = annual_periods(submissions, facts, currency, as_of)
    filing_documents = {row["accessionNumber"]: fact_url(issuer["cik"], row["accessionNumber"]) + row["primaryDocument"]
                        for row in filings if row.get("primaryDocument")}
    balances = {}
    for end in ends:
        balances[end] = {key: select_fact(facts, tags, currency, end, None, as_of, issuer["cik"])
                         for key, (kind, tags) in METRICS.items() if kind == "instant"}
    for period in periods:
        start, end = period["start"], period["end"]
        period["flow_facts"] = {key: select_fact(facts, tags, currency, end, start, as_of, issuer["cik"])
                                if start else {"status": "unknown_annual_start", "valueDecimal": None}
                                for key, (kind, tags) in METRICS.items() if kind == "duration"}
        if amount(period["flow_facts"], "operating_expenses") is None and issuer["analysis"].get("operatingExpenseComponents"):
            period["operating_expense_components"] = {
                key: select_fact(facts, EXPENSE_COMPONENT_TAGS[key], currency, end, start, as_of, issuer["cik"])
                for key in issuer["analysis"]["operatingExpenseComponents"]
            }
        beginning_date = (date.fromisoformat(start) - timedelta(days=1)).isoformat() if start else None
        period["beginning_balance_date"] = beginning_date
        period["calculation_checks"] = checks_for_period(period["flow_facts"], balances[end], balances.get(beginning_date, {}))
        adjustments = {}
        for tag in facts:
            if tag.startswith("IncreaseDecreaseIn") or tag.startswith("AdjustmentsNoncashItems") or tag == "OtherNoncashIncomeExpense":
                selected = select_fact(facts, [tag], currency, end, start, as_of, issuer["cik"]) if start else None
                if selected and selected["status"] == "available":
                    adjustments[tag] = selected
        period["candidate_operating_cash_adjustments"] = adjustments
        period["income_to_operating_cash_status"] = "not_reconciled: candidate adjustment fields require disclosure placement/sign/coverage review"
        period["fact_coverage"] = {key: value["status"] for key, value in period["flow_facts"].items()}
    for selected_facts in [*balances.values(), *(period["flow_facts"] for period in periods),
                           *(period.get("operating_expense_components", {}) for period in periods),
                           *(period["candidate_operating_cash_adjustments"] for period in periods)]:
        for selected in selected_facts.values():
            if selected.get("accession"):
                selected["source_document_url"] = filing_documents.get(selected["accession"])
    changed = []
    for period in periods:
        for key, value in period["flow_facts"].items():
            if value.get("version_values_changed"):
                changed.append({"period_end": period["end"], "metric": key})
    return {"symbol": symbol, "status": "analyzed", "as_of": as_of, "mapping_version": MAPPING_VERSION,
            "issuer": {"cik": issuer["cik"], "name": submissions["name"], "companyfacts_name": companyfacts["entityName"],
                       "identity_check": "CIK matches both responses; ticker listed in submissions", "currency": currency},
            "acquisition": {kind: load_json(directory / f"{symbol}-{kind}.meta.json") for kind in ["submissions", "companyfacts"]},
            "period_count": len(periods), "balance_date_count": len(balances),
            "periods": periods, "balance_facts": balances,
            "balance_calculation_checks": {end: balance_identity(items) for end, items in balances.items()},
            "selected_fact_version_changes": changed,
            "business_dimensions": {"status": "not_provided_by_companyfacts", "note": "No issuer segment/custom-dimensional coverage is inferred from this endpoint."},
            "validation_states": {"structure": "checked expected response keys, issuer CIK/ticker, exact period/unit selection",
                                  "calculation": "only listed Decimal arithmetic identities were evaluated",
                                  "financial_review": "incomplete; placement/sign/scope and taxonomy mapping require source review",
                                  "human_review": "not_performed"},
            "limitations": ["Only recent submissions used; insufficient annual history is reported as a gap.",
                            "Annual selection uses exact actual start/end and annual forms, not source fy/fp alone.",
                            "Latest available annual disclosure is selected per metric; versions and value changes remain visible.",
                            "No missing facts are zero-filled, no residual becomes a financial fact.",
                            "Pretax income including equity-method earnings and pretax income before equity-method earnings are separate concepts.",
                            "PPE purchases, broader productive-asset purchases, net PPE and operating lease ROU are separate metrics.",
                            "Calculation identities do not establish correct financial interpretation or complete source coverage."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default="2026-11-09", help="Disclosure cutoff date, inclusive")
    parser.add_argument("--data-dir", type=Path, help="Explicit snapshot directory; default derives from project root and cutoff")
    parser.add_argument("--fetch", action="store_true", help="Fetch selected issuers' public endpoints; default is offline")
    parser.add_argument("--user-agent", default="FinancialVisualizer/0.1 (local public-filing research)")
    parser.add_argument("--registry", type=Path, help="Explicit issuer configuration; default derives from the project root")
    parser.add_argument("--symbols", nargs="+", help="Registered issuers to inspect; defaults to the configured selection")
    args = parser.parse_args()
    registry = load_registry(args.registry)
    symbols = args.symbols or default_symbols(registry)
    for symbol in symbols:
        get_issuer(symbol, registry)
    date.fromisoformat(args.as_of)
    directory = args.data_dir or PROJECT_ROOT / "data" / "probes" / args.as_of / "sec"
    directory.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        fetch_inputs(directory, args.as_of, args.user_agent, registry, symbols)
    report = {"as_of": args.as_of, "mapping_version": MAPPING_VERSION,
              "issuers": {symbol: analyze_issuer(symbol, directory, args.as_of, registry) for symbol in symbols}}
    save_json(directory / "coverage.json", report)
    for symbol, issuer in report["issuers"].items():
        print(f"{symbol}: {issuer['status']}; annual periods={issuer.get('period_count', 0)}; balance dates={issuer.get('balance_date_count', 0)}")


if __name__ == "__main__":
    main()
