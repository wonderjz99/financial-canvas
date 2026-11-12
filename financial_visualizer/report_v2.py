"""Ticker-to-workspace V2 pipeline. Builds are deterministic and strictly offline."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from scripts.probe_sec import METRICS, select_fact
from .analysis import FLOW_TAGS, BALANCE_TAGS, CF_TAGS
from .core import (FLOW_METRICS, BALANCE_METRICS, _fact, _finalize, _digest,
                   _decimal, _value, _text, _check)
from .filing_xbrl import parse_filing
from .issuers import validate_registry
from .providers import ReportError
from .sec_cache import SecCache, html_validator, json_validator, now, read_json, sha, write_json

VERSION = "financial-visualizer-v2.1"
ROOT = Path(__file__).resolve().parents[1]
ANNUALS = {"10-K", "20-F"}
DIMENSIONS = {"reportable_segment", "service_revenue", "end_market", "geographic_revenue", "revenue_category"}


def symbol_text(value):
    symbol = str(value).strip().upper().removeprefix("US.")
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,19}", symbol):
        raise ReportError("symbol_invalid", "Use one US stock ticker, for example COST.")
    return symbol


def filing_rows(data):
    columns = data.get("filings", {}).get("recent", data)
    if not isinstance(columns.get("form"), list):
        raise ReportError("submissions_invalid", "SEC filing history has no form column.")
    return [{key: values[i] for key, values in columns.items() if isinstance(values, list) and i < len(values)}
            for i in range(len(columns["form"]))]


def annuals(rows, as_of):
    return sorted([r for r in rows if r.get("form") in ANNUALS and r.get("filingDate", "9999") <= as_of
                   and r.get("reportDate")], key=lambda r: (r["reportDate"], r["filingDate"]), reverse=True)


def identify(symbol, tickers, submissions, companyfacts, rows, as_of):
    matches = [r for r in tickers if r["ticker"].upper() == symbol]
    ciks = {str(r["cik"]).zfill(10) for r in matches}
    if len(ciks) != 1:
        raise ReportError("identity_ambiguous", "Ticker must match exactly one SEC issuer.")
    cik = next(iter(ciks))
    if (str(submissions.get("cik")).zfill(10) != cik or str(companyfacts.get("cik")).zfill(10) != cik
            or symbol not in [s.upper() for s in submissions.get("tickers", [])]
            or not submissions.get("name") or not companyfacts.get("entityName")):
        raise ReportError("identity_conflict", "Ticker, submissions and Company Facts issuer identities disagree.")
    try:
        sic = int(submissions["sic"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReportError("industry_unknown", "Cannot confirm the issuer industry (SEC SIC).") from exc
    if not 100 <= sic <= 9999 or 6000 <= sic <= 6999:
        raise ReportError("industry_unsupported", "V2 excludes financial businesses and financial/real-estate SIC 6000–6999.")
    anchors = annuals(rows, as_of)
    if not anchors:
        raise ReportError("period_unknown", "No supported complete 10-K or 20-F annual filing is available.")
    recent_other = [r for r in rows if r.get("form") in {"10-KT", "10-KT/A", "40-F", "40-F/A"}
                    and r.get("filingDate", "9999") <= as_of and r.get("reportDate", "") >= anchors[0]["reportDate"]]
    if recent_other:
        raise ReportError("period_unsupported", "Latest filing uses a transition or unsupported annual reporting form.")
    end = anchors[0]["reportDate"]
    taxonomies = companyfacts.get("facts", {})
    gaap = taxonomies.get("us-gaap", {})
    def current(namespace):
        return any(v.get("end") == end and v.get("form") in {"10-K", "10-K/A", "20-F", "20-F/A"}
                   and v.get("filed", "9999") <= as_of for tag in namespace.values()
                   for unit in tag.get("units", {}).values() for v in unit)
    if not current(gaap) or current(taxonomies.get("ifrs-full", {})):
        raise ReportError("accounting_unsupported", "Current annual US GAAP reporting cannot be confirmed; IFRS is outside V2.")
    currencies = []
    for tags in (["Assets"], METRICS["revenue"][1], ["NetCashProvidedByUsedInOperatingActivities"]):
        currencies.append({unit for tag in tags for unit, values in gaap.get(tag, {}).get("units", {}).items()
                           if re.fullmatch(r"[A-Z]{3}", unit) and any(v.get("end") == end and v.get("form") in {"10-K", "10-K/A", "20-F", "20-F/A"}
                           and v.get("filed", "9999") <= as_of for v in values)})
    common = set.intersection(*currencies)
    if len(common) != 1:
        raise ReportError("currency_unknown", "Annual assets, revenue and operating cash do not identify a unique reporting currency.")
    return {"symbol": symbol, "cik": cik, "name": submissions["name"], "factsName": companyfacts["entityName"],
            "currency": next(iter(common)), "accounting": "US GAAP", "scope": "consolidated",
            "sic": sic, "industry": submissions.get("sicDescription"), "exchanges": submissions.get("exchanges", []),
            "officialWebsites": [submissions[k] for k in ("website", "investorWebsite") if submissions.get(k)]}


def select_periods(rows, gaap, currency, as_of):
    by_end = {}
    for row in annuals(rows, as_of):
        by_end.setdefault(row["reportDate"], row)
    ends = sorted(by_end, reverse=True)[:6]
    result = []
    for end in ends[:5]:
        anchor = by_end[end]
        # Two independent statements must agree on an actual full-year duration.
        sets = []
        for tags in (METRICS["revenue"][1], ["NetCashProvidedByUsedInOperatingActivities"]):
            starts = set()
            for tag in tags:
                for value in gaap.get(tag, {}).get("units", {}).get(currency, []):
                    if (value.get("end") != end or value.get("form") not in {"10-K", "10-K/A", "20-F", "20-F/A"}
                            or value.get("filed", "9999") > as_of or not value.get("start")):
                        continue
                    days = (date.fromisoformat(end) - date.fromisoformat(value["start"])).days + 1
                    if 350 <= days <= 380:
                        starts.add(value["start"])
            sets.append(starts)
        common = set.intersection(*sets)
        if len(common) != 1:
            raise ReportError("period_ambiguous", "Cannot confirm one full-year revenue/cashflow duration ending " + end)
        start = next(iter(common))
        # fy on a comparative fact is the filing year, so only anchor accession FY facts label the period.
        labels = {int(v["fy"]) for tag in gaap.values() for v in tag.get("units", {}).get(currency, [])
                  if v.get("accn") == anchor["accessionNumber"] and v.get("fp") == "FY" and v.get("fy")
                  and v.get("start") == start and v.get("end") == end}
        if len(labels) != 1:
            raise ReportError("fiscal_year_unknown", "Cannot confirm the fiscal year label in its original annual filing: " + end)
        result.append({"year": next(iter(labels)), "start": start, "end": end,
                       "beginningDate": (date.fromisoformat(start) - timedelta(days=1)).isoformat(),
                       "fiscalDays": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1,
                       "anchor": anchor})
    result.reverse()
    if len({p["year"] for p in result}) != len(result):
        raise ReportError("period_ambiguous", "Several annual periods share a fiscal label; manual review is required.")
    for before, after in zip(result, result[1:]):
        if before["end"] != after["beginningDate"]:
            raise ReportError("period_discontinuous", "Annual periods are discontinuous or include an unverified transition.")
    return result


def ticker_rows(data):
    if "fields" in data and "data" in data:
        return [dict(zip(data["fields"], row)) for row in data["data"]]
    return [{**row, "cik": row.get("cik_str")} for row in data.values()]


def _source(workspace, manifest, name):
    record = next((r for r in manifest["sources"] if r["name"] == name), None)
    if record is None:
        raise ReportError("workspace_invalid", "Missing prepared source " + name)
    path = local_file(workspace, record["file"])
    body = path.read_bytes()
    if sha(body) != record["sha256"]:
        raise ReportError("workspace_invalid", "Prepared source hash mismatch: " + name)
    return body


def local_file(workspace, relative):
    path = (workspace / relative).resolve()
    if not path.is_relative_to(workspace.resolve()) or not path.is_file():
        raise ReportError("workspace_invalid", "Evidence must be an existing file inside this workspace.")
    return path


def normalize(workspace, manifest):
    raw = json.loads(_source(workspace, manifest, "companyfacts"), parse_float=Decimal)
    submissions = json.loads(_source(workspace, manifest, "submissions"))
    tickers = ticker_rows(json.loads(_source(workspace, manifest, "tickers")))
    rows = filing_rows(submissions)
    for record in manifest["sources"]:
        if record["name"].startswith("history-"):
            rows.extend(filing_rows(json.loads(_source(workspace, manifest, record["name"]))))
    identity = identify(manifest["symbol"], tickers, submissions, raw, rows, manifest["asOf"])
    periods = select_periods(rows, raw["facts"]["us-gaap"], identity["currency"], manifest["asOf"])
    gaap = raw["facts"]["us-gaap"]
    source_meta = next(r for r in manifest["sources"] if r["name"] == "companyfacts")
    normalized = {"version": VERSION, "identity": identity, "periods": periods, "facts": [], "gaps": []}
    flow_map = {key: METRICS[value][1] for key, value in FLOW_METRICS.items()}
    flow_map.update({"capex": METRICS["purchases_ppe"][1], "productive_asset_purchases": METRICS["purchases_productive_assets"][1], **FLOW_TAGS})
    flow_map["net_income"] = ["ProfitLoss", "NetIncomeLoss"]
    flow_map.update({"raw_" + key: spec[0] for key, spec in CF_TAGS.items()})
    balance_map = {key: METRICS[value][1] for key, value in BALANCE_METRICS.items()}
    # Consolidated equity is preferred over the parent-only amount and never summed with it.
    balance_map["equity"] = ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"]
    for p in periods:
        queries = [(key, tags, p["start"], p["end"]) for key, tags in flow_map.items()]
        queries += [(key, tags, None, p["end"]) for key, tags in balance_map.items()]
        queries += [("begin_" + key, balance_map[key], None, p["beginningDate"]) for key in ("assets", "liabilities", "equity")]
        queries += [("cash_begin", ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], None, p["beginningDate"]),
                    ("cash_end", ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], None, p["end"])]
        for prefix, point in (("begin_", p["beginningDate"]), ("end_", p["end"])):
            queries += [(prefix + key, tags, None, point) for key, tags in BALANCE_TAGS.items()]
        for key, tags, start, end in queries:
            # Total equity and parent equity are different concepts, not interchangeable aliases.
            chosen_tags = tags
            if key in {"equity", "begin_equity", "net_income"}:
                total = select_fact(gaap, tags[:1], identity["currency"], end, start, manifest["asOf"], identity["cik"])
                chosen_tags = tags[:1] if total.get("valueDecimal") is not None else tags[1:]
            selection = select_fact(gaap, chosen_tags, identity["currency"], end, start, manifest["asOf"], identity["cik"])
            fact = _fact(key, selection, identity["currency"], source_meta["retrievedAt"], unit="currency", scope="consolidated",
                         sourceHash=source_meta["sha256"], sourceFile=source_meta["file"], selectionRule="exact_period_latest_annual_disclosure",
                         sourceLabel=gaap.get(selection.get("tag"), {}).get("label"))
            if fact:
                matching = next((r for r in rows if r.get("accessionNumber") == fact["accession"]), None)
                if matching and matching.get("primaryDocument"):
                    fact["sourceUrl"] += quote(matching["primaryDocument"])
                normalized["facts"].append({"year": p["year"], "key": key, "fact": fact})
            else:
                normalized["gaps"].append({"year": p["year"], "key": key, "start": start, "end": end,
                                            "status": selection["status"], "tags": tags, "versions": selection.get("versions", [])})
    return normalized


def registry_for(identity):
    profile = {"cik": identity["cik"], "currency": identity["currency"], "scope": "consolidated",
               "company": {"name": identity["name"], "nameZh": identity["name"]},
               "presentation": {"cashScopeNoteKey": "v2CashScope", "businessNoteKey": "businessNoteGeneric", "sourceSummaryKey": "v2SourceSummary"},
               "business": None, "reconciliations": [], "analysis": {
                   "formation": {"mode": "unavailable", "nonoperatingKeys": [], "pretaxKey": None, "afterTaxKeys": [], "observationKey": None},
                   "notes": {key: None for key in ("profitScope", "cashConversion", "workingCapital", "workingMissing", "quality")},
                   "turnover": [], "assetPurchaseKey": "ppe_purchases", "supplements": [], "cfFromIncome": [], "cfDirect": []}}
    return validate_registry({"schemaVersion": "1.0", "defaultSymbol": identity["symbol"], "defaultSymbols": [identity["symbol"]],
                              "issuers": {identity["symbol"]: profile}})


def prepare(symbol, data_root=None, workspace=None, user_agent=None, offline=False, refresh=False, skip_filings=False):
    symbol = symbol_text(symbol)
    data_root = Path(data_root or ROOT / ".local" / "v2")
    workspace = Path(workspace or data_root / "workspaces" / (symbol + "-" + now().replace(":", "").replace(".", "")))
    if workspace.exists():
        raise ReportError("workspace_exists", "Choose a fresh workspace; prepare never replaces an existing run.")
    workspace.mkdir(parents=True)
    manifest = {"version": VERSION, "symbol": symbol, "asOf": now()[:10], "preparedAt": now(), "sources": [], "warnings": []}
    cache = SecCache(data_root / "cache", user_agent or "FinancialVisualizer/2.0 public-filing research", offline, refresh)
    def acquire(name, url, validator):
        body, meta = cache.get(url, validator)
        suffix = ".html" if name.startswith("filing-") else ".json"
        relative = "sources/" + name + suffix
        target = workspace / relative
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(body)
        manifest["sources"].append({**meta, "name": name, "file": relative})
        return body
    try:
        tickers = ticker_rows(json.loads(acquire("tickers", "https://www.sec.gov/files/company_tickers_exchange.json", json_validator(["fields", "data"]))))
        matches = {str(row["cik"]).zfill(10) for row in tickers if row["ticker"].upper() == symbol}
        if len(matches) != 1:
            raise ReportError("identity_ambiguous", "Ticker must resolve to exactly one issuer in the SEC directory.")
        cik = next(iter(matches))
        submissions = json.loads(acquire("submissions", f"https://data.sec.gov/submissions/CIK{cik}.json", json_validator(["cik", "filings"])))
        acquire("companyfacts", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", json_validator(["cik", "facts"]))
        rows = filing_rows(submissions)
        for item in sorted(submissions["filings"].get("files", []), key=lambda r: r.get("filingTo", ""), reverse=True):
            if len({r["reportDate"] for r in annuals(rows, manifest["asOf"])}) >= 6:
                break
            name = item["name"]
            if not re.fullmatch(r"CIK[0-9]+-submissions-[0-9]+\.json", name):
                raise ReportError("submissions_invalid", "Unexpected historical submissions filename.")
            body = acquire("history-" + name.removesuffix(".json"), "https://data.sec.gov/submissions/" + name, json_validator(["form"]))
            rows.extend(filing_rows(json.loads(body)))
        # A fresh prepare using an old cache must not imply freshly acquired financial data.
        manifest["requestedAsOf"] = manifest["asOf"]
        manifest["asOf"] = min([manifest["asOf"]] + [r["retrievedAt"][:10] for r in manifest["sources"] if r["name"] in {"submissions", "companyfacts"}])
        normalized = normalize(workspace, manifest)
        filing_facts = []
        if not skip_filings:
            for period in normalized["periods"]:
                anchor = period["anchor"]
                accession = anchor["accessionNumber"]
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/" + quote(anchor["primaryDocument"])
                try:
                    body = acquire("filing-" + accession, url, html_validator)
                    candidates, _ = parse_filing(body)
                    filing_facts.append({"sourceName": "filing-" + accession, "year": period["year"], "facts": candidates})
                except ReportError as exc:
                    manifest["warnings"].append({"code": "filing_unavailable", "year": period["year"], "url": url, "detail": exc.message})
        manifest["warnings"].extend(cache.warnings)
        manifest["identity"] = normalized["identity"]
        manifest["normalizedHash"] = sha((json.dumps(normalized, ensure_ascii=False, indent=2) + "\n").encode())
        write_json(workspace / "normalized.json", normalized)
        write_json(workspace / "filing-facts.json", {"version": VERSION, "filings": filing_facts})
        write_json(workspace / "supplements.json", {"version": VERSION, "sources": [], "facts": [], "business": [], "reconciliations": [], "notes": []})
        write_json(workspace / "workspace.json", manifest)
        report, registry, checks = build_workspace(workspace, write_checks=False)
        write_json(workspace / "checks.json", checks)
        tasks = {"version": VERSION, "identity": normalized["identity"], "periods": normalized["periods"],
                 "gaps": normalized["gaps"], "warnings": manifest["warnings"], "checks": checks,
                 "research": [{"year": p["year"], "topics": ["segment_or_revenue_categories", "complete_cfo_adjustments", "cash_and_restricted_cash_scope", "nonoperating_income_formation", "restatements_and_comparability"],
                                "filing": p["anchor"]} for p in normalized["periods"]]}
        write_json(workspace / "research-tasks.json", tasks)
        return {"workspace": str(workspace.resolve()), "symbol": symbol, "identity": normalized["identity"],
                "years": report["years"], "normalized": str((workspace / "normalized.json").resolve()),
                "checks": str((workspace / "checks.json").resolve()), "researchTasks": str((workspace / "research-tasks.json").resolve()),
                "supplements": str((workspace / "supplements.json").resolve()), "warnings": manifest["warnings"]}
    except (ReportError, OSError, ValueError, KeyError, TypeError) as exc:
        write_json(workspace / "prepare-error.json", {"code": getattr(exc, "code", "prepare_failed"), "message": str(exc), "at": now()})
        raise


def _derive(key, left, right, currency, retrieved_at, sign=-1):
    if not left or not right:
        return None
    inputs = [left["factId"], right["factId"]]
    value = _text(_value(left) + sign * _value(right))
    source = {"factId": "derived-" + _digest([VERSION, key, inputs, value])[:24], "valueDecimal": value, "unit": currency,
              "start": left["start"], "end": left["end"], "status": "derived", "inputs": inputs,
              "formula": left["key"] + (" - " if sign == -1 else " + ") + right["key"]}
    return _fact(key, source, currency, retrieved_at, unit="currency", scope="consolidated")


def build_workspace(workspace, write_checks=True):
    from .research import apply_research
    from .analysis import augment_report
    workspace = Path(workspace).resolve()
    manifest = read_json(workspace / "workspace.json")
    if manifest.get("version") != VERSION:
        raise ReportError("workspace_invalid", "Unsupported V2 workspace version; run prepare again.")
    # Verify every source, even those not used in the current chart.
    for record in manifest["sources"]:
        _source(workspace, manifest, record["name"])
    normalized = normalize(workspace, manifest)
    if normalized["identity"] != manifest["identity"]:
        raise ReportError("workspace_invalid", "Workspace issuer identity differs from verified SEC sources.")
    saved = read_json(workspace / "normalized.json")
    if normalized != saved or sha((workspace / "normalized.json").read_bytes()) != manifest["normalizedHash"]:
        raise ReportError("workspace_invalid", "Normalized facts changed; put reviewed observations in supplements.json.")
    identity = normalized["identity"]
    registry = registry_for(identity)
    snapshot_id = "v2-" + _digest([manifest["sources"], normalized])[:24]
    report = {"schemaVersion": "1.0", "methodVersion": VERSION, "symbol": identity["symbol"],
              "company": {**registry["issuers"][identity["symbol"]]["company"], "currency": identity["currency"], "cik": identity["cik"]},
              "presentation": registry["issuers"][identity["symbol"]]["presentation"],
              "snapshot": {"id": snapshot_id, "mode": "prepared", "asOf": manifest["asOf"], "retrievedAt": max(r["retrievedAt"] for r in manifest["sources"]), "preparedAt": manifest["preparedAt"],
                           "sources": manifest["sources"], "warnings": manifest["warnings"]},
              "years": [p["year"] for p in normalized["periods"]], "periods": [], "facts": {}, "comparisons": [],
              "warnings": ["limited_financial_review"], "overrides": [], "validation": {"structure": "checked", "calculation": "per_formula", "financialReview": "limited", "humanReview": "not_performed"}}
    by_year = {year: {} for year in report["years"]}
    for row in normalized["facts"]:
        by_year[row["year"]][row["key"]] = row["fact"]
    for p in normalized["periods"]:
        selected = by_year[p["year"]]
        keys = [*FLOW_METRICS, *BALANCE_METRICS, "begin_assets", "begin_liabilities", "begin_equity", "cash_begin", "cash_end", "capex", "productive_asset_purchases"]
        period = {**{key: p[key] for key in ("year", "start", "end", "beginningDate", "fiscalDays")},
                  "metrics": {key: selected.get(key) for key in keys}, "sourceChecks": [],
                  "business": {"status": "unavailable", "items": [], "missing": ["official_business_disclosure"], "checks": [], "dimension": None},
                  "reconciliation": {"status": "partial", "items": [], "missing": ["complete_operating_adjustments"], "check": None}}
        report["periods"].append(period)
    research = apply_research(workspace, manifest, report, by_year, normalized["gaps"])
    for p in report["periods"]:
        m = p["metrics"]
        # Arithmetic identities only, never an inferred cash adjustment or a balancing item.
        if not m["gross_profit"]:
            m["gross_profit"] = _derive("gross_profit", m["revenue"], m["cost_of_revenue"], identity["currency"], manifest["preparedAt"])
        if not m["operating_expenses"]:
            m["operating_expenses"] = _derive("operating_expenses", m["gross_profit"], m["operating_income"], identity["currency"], manifest["preparedAt"])
        for name, keys, left, right in (("revenue_minus_cost_equals_gross", ["revenue", "cost_of_revenue", "gross_profit"], _value(m["revenue"]) - _value(m["cost_of_revenue"]) if m["revenue"] and m["cost_of_revenue"] else None, _value(m["gross_profit"])),
                                        ("pretax_minus_tax_equals_net", ["pretax_income", "income_tax", "net_income"], _value(m["pretax_income"]) - _value(m["income_tax"]) if m["pretax_income"] and m["income_tax"] else None, _value(m["net_income"]))):
            p["sourceChecks"].append(_check(name, left, right, [m[key]["factId"] for key in keys if m[key]]))
    _finalize(report, registry)
    # Keep original SEC facts available behind reviewed aliases and explicit version resolutions.
    for row in normalized["facts"]:
        report["facts"].setdefault(row["fact"]["factId"], row["fact"])
    prepared = {(year, key): fact for year, facts in by_year.items() for key, fact in facts.items()}
    issuer = {"issuer": {"cik": identity["cik"]}}
    augment_report(report, issuer, issuer_config=registry["issuers"][identity["symbol"]], prepared_facts=prepared, include_legacy=False, formation_policies=research["formationPolicies"])
    for p in report["periods"]:
        p["balance"]["equityBasis"] = p["metrics"]["equity"]["tag"] if p["metrics"].get("equity") else "unknown"
        equity_chart = next(section for section in p["analysis"]["sections"] if section["id"] == "cash_uses")["equityChart"]
        equity_chart["scope"] = p["balance"]["equityBasis"]
        if p["year"] in research["formationPolicies"]:
            profit_section = next(section for section in p["analysis"]["sections"] if section["id"] == "profit")
            if any(c["name"] == "disclosed_nonoperating_to_pretax" and c["status"] == "mismatch" for c in profit_section["checks"]):
                profit_section["status"] = "conflict"
    # Restoring the reviewed reconciliation is unnecessary: augment_report retains eligible row sets.
    report["delivery"] = {"mode": "single_company", "identity": identity, "gaps": normalized["gaps"], "research": research,
                          "notes": research["notes"], "status": "partial", "sourceCutoff": manifest["asOf"]}
    checks = {"version": VERSION, "status": "partial", "identity": "verified_against_sec", "years": report["years"],
              "checks": [{"year": p["year"], **check} for p in report["periods"] for check in p["checks"]],
              "analysisChecks": [{"year": p["year"], "section": section["id"], **check} for p in report["periods"] for section in p["analysis"]["sections"] for check in section["checks"]],
              "missing": [{"year": p["year"], "metrics": p["missingMetrics"], "business": p["business"]["status"], "cfo": p["reconciliation"]["status"]} for p in report["periods"]],
              "research": research, "warnings": manifest["warnings"]}
    if any(c["status"] == "mismatch" for c in checks["checks"]) or any(section["status"] == "conflict" for p in report["periods"] for section in p["analysis"]["sections"]):
        checks["status"] = "conflict"
        report["delivery"]["status"] = "conflict"
    if write_checks:
        write_json(workspace / "checks.json", checks)
    return report, registry, checks
