"""Build source-bound local financial reports using fixed Decimal calculations."""

from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from urllib.parse import urlparse

from .providers import ROOT, SEED_ROOT, ReportError, load_snapshot, normalize_symbol
from .issuers import RegistryError, get_issuer

SCHEMA_VERSION = "1.0"
METHOD_VERSION = "report-core-1"
LOCALE = json.loads((Path(__file__).parent / "resources" / "zh-CN.json").read_text(encoding="utf-8"))
FLOW_METRICS = {
    "revenue": "revenue", "cost_of_revenue": "cost_of_revenue", "gross_profit": "gross_profit",
    "operating_expenses": "operating_expenses", "operating_income": "operating_income",
    "pretax_income": "pretax_income", "income_tax": "income_tax", "net_income": "net_income",
    "cfo": "operating_cash", "cfi": "investing_cash", "cff": "financing_cash",
    "fx": "cash_fx", "cash_change": "cash_change_including_fx", "sbc": "stock_based_compensation",
}
BALANCE_METRICS = {
    "assets": "assets", "liabilities": "liabilities", "equity": "equity_parent",
    "bs_cash": "cash_and_equivalents", "ppe": "ppe_net", "rou": "operating_lease_rou_asset",
}
OVERRIDE_METRICS = frozenset((*FLOW_METRICS, *BALANCE_METRICS, "cash_begin", "cash_end", "capex"))
CURRENCY_SYMBOLS = {"USD": "$", "CNY": "¥"}


def _decimal(value):
    if value is None:
        return None
    if isinstance(value, (float, bool)):
        raise ReportError("invalid_amount", "Financial amounts must be decimal strings.")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ReportError("invalid_amount", "A finite decimal amount is required.") from exc
    if not parsed.is_finite() or parsed.copy_abs() > Decimal("1e30") or parsed.as_tuple().exponent < -18:
        raise ReportError("invalid_amount", "Amount is nonfinite or outside the supported range.")
    return parsed


def _text(value):
    return format(value, "f") if value is not None else None


def format_amount(value, currency, compact=False):
    amount = _decimal(value)
    if amount is None:
        return LOCALE["notAvailable"]
    prefix = CURRENCY_SYMBOLS.get(currency, currency + " ")
    with localcontext() as context:
        context.prec = 64
        if compact:
            scaled = (amount / Decimal(100000000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return f"{prefix}{scaled:,.2f}{LOCALE['hundredMillion']}"
        rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return prefix + f"{rounded:,.2f}".removesuffix(".00")


def _percent(value):
    if value is None:
        return LOCALE["notAvailable"]
    return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}%"


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fact(key, source, currency, retrieved_at, source_name="SEC", **extra):
    if not source or source.get("valueDecimal") is None:
        return None
    value = _decimal(source["valueDecimal"])
    fact = {
        "factId": source.get("factId") or f"{source_name.lower()}-{_digest(source)[:24]}",
        "key": key, "valueDecimal": _text(value), "displayValue": format_amount(value, currency),
        "shortValue": format_amount(value, currency, True), "currency": currency,
        "start": source.get("start"), "end": source.get("end"),
        "source": source_name, "sourceUrl": source.get("source_document_url") or source.get("source_url"),
        "tag": source.get("tag"), "accession": source.get("accession"), "filed": source.get("filed"),
        "retrievedAt": retrieved_at, "status": source.get("status", "available"),
        "rawValue": source.get("valueDecimal"), "rawUnit": source.get("unit", currency),
        "sourceMultiplier": "1" if source_name == "SEC" else None,
        "documentMultiplier": None, "scope": source.get("entity_scope", "consolidated"),
        "formula": source.get("formula"), "inputs": source.get("inputs", []),
        "versions": source.get("versions", []), "versionValuesChanged": source.get("version_values_changed", False),
        "validation": {"structure": "checked", "calculation": "not_applicable",
                       "financialReview": "limited", "humanReview": "not_performed"},
        **extra,
    }
    if fact["status"] == "derived":
        fact["source"] = "calculated"
        fact["validation"]["calculation"] = "fixed_formula"
        fact["rawValue"] = None
    if source_name == "IR_manual" and extra.get("originalMultiplier"):
        multiplier = _decimal(extra["originalMultiplier"])
        fact["observationValueDecimal"] = fact["valueDecimal"]
        fact["originalDocumentValue"] = _text(value / multiplier)
        fact["rawValue"] = fact["originalDocumentValue"]
        fact["sourceMultiplier"] = str(extra["originalMultiplier"])
        fact["documentMultiplier"] = str(extra["originalMultiplier"])
        fact["rawValueKind"] = "document_amount"
    return fact


def _value(fact):
    return _decimal(fact["valueDecimal"]) if fact else None


def _ratio(numerator, denominator):
    left, right = _value(numerator), _value(denominator)
    if left is None or right is None or right <= 0:
        return {"valueDecimal": None, "displayValue": LOCALE["notAvailable"], "status": "not_applicable",
                "inputs": [fact["factId"] for fact in (numerator, denominator) if fact]}
    value = left / right * Decimal(100)
    return {"valueDecimal": _text(value), "displayValue": _percent(value), "status": "calculated",
            "inputs": [numerator["factId"], denominator["factId"]]}


def _check(name, left, right, inputs, semantic="arithmetic_only"):
    if left is None or right is None:
        return {"name": name, "status": "unknown", "differenceDecimal": None, "inputs": inputs, "scope": semantic}
    difference = left - right
    return {"name": name, "status": "match" if difference == 0 else "mismatch",
            "differenceDecimal": _text(difference), "inputs": inputs, "scope": semantic}


def _load_business(symbol, year, start, end, currency, revenue, issuer_config=None):
    configuration = issuer_config if issuer_config is not None else get_issuer(symbol)
    business = configuration["business"]
    path = SEED_ROOT / "futu" / f"{symbol}-breakdown-{year}.json"
    empty = {"status": "unavailable", "source": "Futu", "dimension": business["dimension"] if business else None,
             "items": [], "missing": ["business_period"], "checks": []}
    if not business or not path.exists() or revenue is None:
        return empty
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    try:
        payload = json.loads(wrapper["response"]["content"][0]["text"], parse_float=Decimal)
        data = payload["data"]
    except (KeyError, ValueError, IndexError) as exc:
        raise ReportError("supplement_invalid", "Saved business supplement is invalid.", 500) from exc
    if payload.get("ret_code") != 0 or wrapper["request"].get("financial_type") != 7 or wrapper["request"].get("symbol") != f"US.{symbol}" or data.get("period") != f"{year}/FY" or data.get("currency_code") != currency:
        return {**empty, "status": "conflict", "missing": ["business_period_or_currency"]}
    group = next((row for row in data.get("breakdown_list", []) if row.get("type") == business["sourceGroupType"]), None)
    if not group or not group.get("item_list"):
        return empty
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    items = []
    total = Decimal(0)
    for row in group["item_list"]:
        value = _decimal(row.get("main_oper_income"))
        if value is None or value < 0:
            return {**empty, "status": "conflict", "missing": ["business_negative_or_unknown"]}
        total += value
        name = row["name"]
        identity = hashlib.sha256(name.encode()).hexdigest()[:12]
        source = {"factId": f"futu-{digest[:16]}-{identity}", "valueDecimal": _text(value), "unit": currency,
                  "start": start, "end": end, "status": "available", "tag": "business:" + name,
                  "source_url": "https://openapi.futunn.com/futu-api-doc/quote/get-financials-revenue-breakdown.html"}
        fact = _fact("business_revenue", source, currency, wrapper["retrievedAt"], "Futu", name=name, id=identity,
                     dimension=empty["dimension"], originalPeriod=data["period"],
                     periodMapping="SEC annual start/end anchor; provider did not return the start date.",
                     sourceFile=path.relative_to(ROOT).as_posix(), sourceHash=digest)
        share = value / _value(revenue) * Decimal(100) if _value(revenue) > 0 else None
        fact.update(shareDecimal=_text(share), shareDisplay=_percent(share))
        fact["presentation"] = copy.deepcopy(business["items"].get(name, {"color": "blue"}))
        items.append(fact)
    check = _check("business_sum_equals_revenue", total, _value(revenue), [fact["factId"] for fact in items] + [revenue["factId"]])
    return {**empty, "status": "partial" if check["status"] == "match" else "conflict", "items": items,
            "missing": ["business_full_source_semantics"] if check["status"] == "match" else ["business_sum"],
            "checks": [check], "sourceAsOf": "2026-11-09", "sourcePeriod": data["period"]}


def _load_reconciliation(symbol, period, metrics, retrieved_at, issuer_config=None):
    result = {"status": "partial", "items": [], "missing": ["complete_operating_adjustments"], "check": None}
    configuration = issuer_config if issuer_config is not None else get_issuer(symbol)
    selection = next((row for row in configuration["reconciliations"] if (row["start"], row["end"]) == (period["start"], period["end"])), None)
    if not selection or not metrics.get("cfo") or not metrics.get("net_income"):
        return result
    path = ROOT / selection["sourceFile"]
    if not path.exists():
        return result
    data = json.loads(path.read_text(encoding="utf-8"))
    check = next((row for row in data.get("manual_text_checks", []) if row["id"] == selection["checkId"]), None)
    if not check:
        return result
    source = next((row for row in data["sources"] if row["id"] == check["source_id"]), None)
    if not source or (source.get("period", {}).get("start"), source.get("period", {}).get("end")) != (period["start"], period["end"]):
        return {**result, "status": "conflict", "missing": ["reconciliation_source_period"]}
    if source["display_currency"] != metrics["cfo"]["currency"]:
        return result
    digest = _digest(check)[:16]
    items = []
    for item in check["inputs"]:
        fact = _fact(item["key"], {"factId": f"ir-{digest}-{item['key']}", "valueDecimal": item["valueDecimal"],
                                 "start": period["start"], "end": period["end"], "unit": source["display_currency"],
                                 "status": "manually_selected", "source_url": source["url"]},
                     source["display_currency"], source["retrieved_at"], "IR_manual",
                     nameKey=item["key"], kind="profit" if item["key"] == "net_income" else "noncash" if item["key"] in selection["noncashKeys"] else "working_capital",
                     location=check["location"], originalMultiplier=source["display_multiplier"], acquisitionMethod=data["acquisition_method"])
        items.append(fact)
    total = sum((_value(fact) for fact in items), Decimal(0))
    arithmetic = _check("manual_ir_adjustments_equal_cfo", total, _value(metrics["cfo"]), [fact["factId"] for fact in items] + [metrics["cfo"]["factId"]])
    profit_matches = bool(metrics["net_income"] and items[0]["valueDecimal"] == metrics["net_income"]["valueDecimal"])
    if profit_matches:
        items[0]["equivalentFactId"] = metrics["net_income"]["factId"]
    return {"status": "eligible" if arithmetic["status"] == "match" and profit_matches else "conflict",
            "items": items, "missing": [] if arithmetic["status"] == "match" and profit_matches else ["ir_source_version_difference"],
            "check": arithmetic, "acquisitionMethod": data["acquisition_method"], "sourcePeriod": source["period"]}


def _finish_period(period):
    metrics = period["metrics"]
    for key in ("revenue", "cost_of_revenue", "gross_profit", "operating_expenses", "operating_income", "pretax_income", "income_tax", "net_income"):
        if metrics.get(key):
            share = _ratio(metrics[key], metrics.get("revenue"))
            metrics[key].update(shareDecimal=share["valueDecimal"], shareDisplay=share["displayValue"])
    for key in ("assets", "liabilities", "equity", "bs_cash", "ppe", "rou"):
        if metrics.get(key):
            share = _ratio(metrics[key], metrics.get("assets"))
            metrics[key].update(assetShareDecimal=share["valueDecimal"], assetShareDisplay=share["displayValue"])
    required_profit = ("revenue", "cost_of_revenue", "gross_profit", "operating_expenses", "operating_income", "net_income")
    period["profit"] = {"status": "partial", "items": [metrics[key] for key in (*required_profit[:5], "pretax_income", "income_tax", "net_income") if metrics.get(key)],
                        "missing": [key for key in required_profit if not metrics.get(key)] + ["full_nonoperating_breakdown"]}
    cash_required = ("cash_begin", "cfo", "cfi", "cff", "cash_end", "fx")
    cash_missing = [key for key in cash_required if not metrics.get(key)]
    cash_inputs = [metrics.get(key) for key in cash_required]
    total = None if any(fact is None for fact in cash_inputs) else sum((_value(metrics[key]) for key in ("cash_begin", "cfo", "cfi", "cff", "fx")), Decimal(0))
    cash_check = _check("cash_bridge", total, _value(metrics.get("cash_end")), [fact["factId"] for fact in cash_inputs if fact])
    cash_status = "partial" if cash_missing else "eligible" if cash_check["status"] == "match" else "conflict"
    period["cash"] = {"status": cash_status, "begin": metrics.get("cash_begin"), "cfo": metrics.get("cfo"),
                      "cfi": metrics.get("cfi"), "cff": metrics.get("cff"), "fx": metrics.get("fx"),
                      "end": metrics.get("cash_end"), "change": metrics.get("cash_change"),
                      "missing": cash_missing, "scope": "cash_equivalents_and_restricted_cash", "check": cash_check}
    period["cash"]["steps"] = []
    if cash_status == "eligible":
        cursor = _value(metrics["cash_begin"])
        steps = [{"key": "cash_begin", "kind": "total", "factId": metrics["cash_begin"]["factId"],
                  "startDecimal": "0", "endDecimal": _text(cursor), "displayValue": metrics["cash_begin"]["shortValue"]}]
        for key in ("cfo", "cfi", "cff", "fx"):
            following = cursor + _value(metrics[key])
            steps.append({"key": key, "kind": "flow", "factId": metrics[key]["factId"],
                          "startDecimal": _text(cursor), "endDecimal": _text(following), "displayValue": metrics[key]["shortValue"]})
            cursor = following
        steps.append({"key": "cash_end", "kind": "total", "factId": metrics["cash_end"]["factId"],
                      "startDecimal": "0", "endDecimal": metrics["cash_end"]["valueDecimal"], "displayValue": metrics["cash_end"]["shortValue"]})
        period["cash"]["steps"] = steps
    reconciliation = period["reconciliation"]
    reconciliation["steps"] = []
    if reconciliation["status"] == "eligible":
        cursor = Decimal(0)
        for index, item in enumerate(reconciliation["items"]):
            following = cursor + _value(item)
            reconciliation["steps"].append({"key": item["nameKey"], "kind": "total" if index == 0 else "flow", "factId": item["factId"],
                                             "startDecimal": "0" if index == 0 else _text(cursor), "endDecimal": _text(following),
                                             "displayValue": item["shortValue"]})
            cursor = following
        reconciliation["steps"].append({"key": "cfo", "kind": "total", "factId": metrics["cfo"]["factId"],
                                         "startDecimal": "0", "endDecimal": metrics["cfo"]["valueDecimal"], "displayValue": metrics["cfo"]["shortValue"]})
    balance_values = [metrics.get(key) for key in ("assets", "liabilities", "equity")]
    balance_check = _check("assets_equals_liabilities_plus_equity", _value(metrics.get("assets")),
                           _value(metrics["liabilities"]) + _value(metrics["equity"]) if all(balance_values) else None,
                           [fact["factId"] for fact in balance_values if fact])
    period["balance"] = {"status": "eligible" if balance_check["status"] == "match" else "partial",
                         **{key: metrics.get(key) for key in ("assets", "liabilities", "equity", "ppe", "rou")},
                         "cash": metrics.get("bs_cash"), "check": balance_check,
                         "equityBasis": "parent_equity; arithmetic identity checked, NCI semantic review remains limited"}
    period["ratios"] = {"net_margin": _ratio(metrics.get("net_income"), metrics.get("revenue")),
                        "gross_margin": _ratio(metrics.get("gross_profit"), metrics.get("revenue")),
                        "cash_conversion": _ratio(metrics.get("cfo"), metrics.get("net_income"))}
    period["views"] = {"profit": period["profit"]["status"], "cash": cash_status,
                       "balance": period["balance"]["status"], "business": period["business"]["status"],
                       "reconciliation": period["reconciliation"]["status"], "overview": "partial"}
    period["checks"] = [*period.get("sourceChecks", []), cash_check, balance_check, *period["business"].get("checks", [])]
    if period["reconciliation"].get("check"):
        period["checks"].append(period["reconciliation"]["check"])
    insights = [{"key": "historical_period", "params": {"start": period["start"], "end": period["end"]}, "refs": []}]
    if metrics.get("cash_end") and metrics.get("bs_cash") and metrics["cash_end"]["valueDecimal"] != metrics["bs_cash"]["valueDecimal"]:
        insights.append({"key": "cash_scope_includes_restricted", "params": {}, "refs": [metrics["cash_end"]["factId"], metrics["bs_cash"]["factId"]]})
    if period["reconciliation"]["status"] != "eligible":
        insights.append({"key": "operating_adjustments_incomplete", "params": {}, "refs": [metrics[key]["factId"] for key in ("net_income", "cfo") if metrics.get(key)]})
    if cash_missing:
        insights.append({"key": "cash_effect_unknown", "params": {"missing": cash_missing}, "refs": []})
    period["insights"] = insights
    period["missingMetrics"] = [key for key, fact in metrics.items() if fact is None]


def _comparisons(periods, currency):
    results = []
    keys = ("revenue", "net_income", "cfo", "assets", "cash_end", "operating_income")
    for before in periods:
        for after in periods:
            values = {}
            for key in keys:
                first, last = _value(before["metrics"].get(key)), _value(after["metrics"].get(key))
                delta = last - first if first is not None and last is not None else None
                percent = delta / first * Decimal(100) if delta is not None and first > 0 else None
                values[key] = {"deltaDecimal": _text(delta), "percentDecimal": _text(percent),
                               "displayDelta": (("+" if delta > 0 else "") + format_amount(delta, currency, True)) if delta is not None else LOCALE["notAvailable"],
                               "displayPercent": (("+" if percent > 0 else "") + _percent(percent)) if percent is not None else LOCALE["notAvailable"],
                               "status": "calculated" if delta is not None else "unknown",
                               "percentStatus": "calculated" if percent is not None else "not_applicable"}
            results.append({"fromYear": before["year"], "toYear": after["year"], "metrics": values})
    return results


def _finalize(report, registry=None):
    facts = {}
    for period in report["periods"]:
        had_analysis = period.pop("analysis", None)
        if had_analysis and period["reconciliation"].get("profileId"):
            # Reviewed profiles are rebuilt after normalization; direct overrides
            # must not retain groups computed from the previous fact registry.
            period["reconciliation"] = {"status": "partial", "items": [], "steps": [],
                                         "missing": ["complete_operating_adjustments"], "check": None}
        if had_analysis and period["reconciliation"]["status"] != "eligible":
            period["reconciliation"]["items"] = []
            period["reconciliation"]["steps"] = []
            period["reconciliation"]["check"] = None
        _finish_period(period)
        for fact in [*period["metrics"].values(), *period["business"]["items"], *period["reconciliation"]["items"]]:
            if fact:
                facts.setdefault(fact["factId"], fact)
    report["facts"] = facts
    report.pop("analysisLocale", None)
    report["comparisons"] = _comparisons(report["periods"], report["company"]["currency"])
    report["missingFields"] = [{"year": period["year"], "metric": key, "currency": report["company"]["currency"],
                                "start": None if key in BALANCE_METRICS or key in {"cash_begin", "cash_end"} else period["start"],
                                "end": period["beginningDate"] if key == "cash_begin" else period["end"]}
                               for period in report["periods"] for key in period["missingMetrics"] if key in OVERRIDE_METRICS]
    validate_report(report, registry)
    return report


def build_report(symbol, data_root=None, refresh=False, overrides=None, registry=None):
    symbol = normalize_symbol(symbol, registry)
    configuration = get_issuer(symbol, registry)
    issuer, snapshot = load_snapshot(symbol, data_root, refresh, registry=registry)
    currency = issuer["issuer"]["currency"]
    report = {"schemaVersion": SCHEMA_VERSION, "methodVersion": METHOD_VERSION, "symbol": symbol,
              "company": {**configuration["company"], "cik": issuer["issuer"]["cik"], "currency": currency},
              "presentation": copy.deepcopy(configuration["presentation"]),
              "snapshot": snapshot, "years": [], "periods": [], "facts": {}, "comparisons": [],
              "warnings": ["limited_financial_review", "supplement_source_is_snapshot"], "overrides": [],
              "validation": {"structure": "checked", "calculation": "per_formula", "financialReview": "limited", "humanReview": "not_performed"}}
    for source_period in sorted(issuer["periods"], key=lambda row: row["end"]):
        flows = source_period["flow_facts"]
        metrics = {key: _fact(key, flows.get(source_key), currency, snapshot["retrievedAt"]) for key, source_key in FLOW_METRICS.items()}
        if metrics["gross_profit"] is None:
            metrics["gross_profit"] = _fact("gross_profit", flows.get("gross_profit_derived"), currency, snapshot["retrievedAt"])
        if metrics["operating_expenses"] is None and source_period.get("operating_expense_components"):
            components = {key: _fact(key, value, currency, snapshot["retrievedAt"])
                          for key, value in source_period["operating_expense_components"].items()}
            if all(components.values()):
                metrics.update(components)
                inputs = [fact["factId"] for fact in components.values()]
                value = _text(sum((_value(fact) for fact in components.values()), Decimal(0)))
                formula = " + ".join(components)
                metrics["operating_expenses"] = _fact("operating_expenses", {
                    "factId": "derived-" + _digest(["operating_expenses", inputs, value])[:24],
                    "valueDecimal": value, "unit": currency, "start": source_period["start"],
                    "end": source_period["end"], "status": "derived", "formula": formula, "inputs": inputs,
                }, currency, snapshot["retrievedAt"])
        ending = issuer["balance_facts"].get(source_period["end"], {})
        beginning = issuer["balance_facts"].get(source_period["beginning_balance_date"], {})
        metrics.update({key: _fact(key, ending.get(source_key), currency, snapshot["retrievedAt"]) for key, source_key in BALANCE_METRICS.items()})
        for key, source_key in (("begin_assets", "assets"), ("begin_liabilities", "liabilities"), ("begin_equity", "equity_parent")):
            metrics[key] = _fact(key, beginning.get(source_key), currency, snapshot["retrievedAt"])
        metrics["cash_begin"] = _fact("cash_begin", beginning.get("cash_including_restricted"), currency, snapshot["retrievedAt"])
        metrics["cash_end"] = _fact("cash_end", ending.get("cash_including_restricted"), currency, snapshot["retrievedAt"])
        capex = flows.get("purchases_ppe")
        metrics["capex"] = _fact("capex", capex, currency, snapshot["retrievedAt"])
        metrics["productive_asset_purchases"] = _fact("productive_asset_purchases", flows.get("purchases_productive_assets"), currency, snapshot["retrievedAt"])
        year = source_period["fiscal_year"]
        period = {"year": year, "start": source_period["start"], "end": source_period["end"],
                  "beginningDate": source_period["beginning_balance_date"], "metrics": metrics,
                  "sourceChecks": source_period["calculation_checks"],
                  "business": _load_business(symbol, year, source_period["start"], source_period["end"], currency, metrics["revenue"], configuration),
                  "reconciliation": _load_reconciliation(symbol, source_period, metrics, snapshot["retrievedAt"], configuration)}
        report["periods"].append(period)
        report["years"].append(year)
    _finalize(report, registry)
    if overrides:
        report = apply_overrides(report, overrides, registry)
    from .analysis import augment_report
    return augment_report(report, issuer, data_root, issuer_config=configuration)


def validate_report(report, registry=None):
    try:
        configuration = get_issuer(report.get("symbol"), registry)
    except RegistryError as exc:
        raise ReportError("report_invalid", "Report issuer is not registered.", 500) from exc
    if report.get("schemaVersion") != SCHEMA_VERSION:
        raise ReportError("report_invalid", "Report identity is invalid.", 500)
    if report.get("company", {}).get("currency") != configuration["currency"] or report.get("company", {}).get("cik") != configuration["cik"]:
        raise ReportError("report_invalid", "Report identity or currency differs from the issuer registry.", 500)
    if not report.get("periods") or report["years"] != sorted(set(report["years"])):
        raise ReportError("report_invalid", "Report annual periods are invalid.", 500)
    for period in report["periods"]:
        for fact in period["metrics"].values():
            if fact is not None:
                if not isinstance(fact.get("valueDecimal"), str) or fact.get("currency") != report["company"]["currency"]:
                    raise ReportError("report_invalid", "Financial fact currency or decimal representation is invalid.", 500)
                _decimal(fact["valueDecimal"])
    return report


def validate_override(report, entry):
    if not isinstance(entry, dict):
        raise ReportError("invalid_override", "A financial override object is required.")
    year, metric = entry.get("year"), entry.get("metric")
    if isinstance(year, bool) or year not in report["years"] or metric not in OVERRIDE_METRICS:
        raise ReportError("invalid_override", "Override period or metric is not supported.")
    period = next(row for row in report["periods"] if row["year"] == year)
    if period["metrics"].get(metric) is not None:
        raise ReportError("override_existing_fact", "Overrides may fill missing facts only.", 409)
    if not isinstance(entry.get("valueDecimal"), str) or len(entry["valueDecimal"]) > 100:
        raise ReportError("invalid_override", "Override amount must be a decimal string.")
    value = _decimal(entry["valueDecimal"])
    if value is None:
        raise ReportError("invalid_override", "Override amount cannot be null.")
    if metric == "capex" and value < 0:
        raise ReportError("invalid_override", "Capital purchases must be a nonnegative amount.")
    expected_start = None if metric in BALANCE_METRICS or metric in {"cash_begin", "cash_end"} else period["start"]
    expected_end = period["beginningDate"] if metric == "cash_begin" else period["end"]
    if entry.get("currency") != report["company"]["currency"] or entry.get("start") != expected_start or entry.get("end") != expected_end:
        raise ReportError("invalid_override", "Override currency and actual period must match the missing fact.")
    source_url = entry.get("sourceUrl", "")
    if not isinstance(source_url, str) or len(source_url) > 2000:
        raise ReportError("invalid_override", "A source URL is required.")
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ReportError("invalid_override", "Source URL must be an HTTP(S) document without credentials.")
    note = entry.get("note", "")
    if not isinstance(note, str) or not note.strip() or len(note) > 2000:
        raise ReportError("invalid_override", "A source location or explanation is required.")
    return {"year": year, "metric": metric, "valueDecimal": _text(value), "currency": entry["currency"],
            "start": expected_start, "end": expected_end, "sourceUrl": source_url,
            "note": note.strip(), "recordedAt": entry.get("recordedAt")}


def apply_overrides(report, overrides, registry=None):
    if not isinstance(overrides, list) or len(overrides) > 100:
        raise ReportError("invalid_override", "At most 100 explicit financial overrides are supported.")
    updated = copy.deepcopy(report)
    normalized = []
    for entry in overrides:
        item = validate_override(updated, entry)
        period = next(row for row in updated["periods"] if row["year"] == item["year"])
        source = {"factId": "manual-" + _digest(item)[:24], "valueDecimal": item["valueDecimal"], "unit": item["currency"],
                  "start": item["start"], "end": item["end"], "status": "manual", "source_url": item["sourceUrl"]}
        fact = _fact(item["metric"], source, item["currency"], item.get("recordedAt"), "Manual", note=item["note"])
        period["metrics"][item["metric"]] = fact
        normalized.append(item)
    updated["overrides"] = normalized
    updated["snapshot"]["baseId"] = report["snapshot"].get("baseId", report["snapshot"]["id"])
    updated["snapshot"]["id"] = updated["snapshot"]["baseId"] + "-" + _digest(normalized)[:12]
    if normalized:
        updated["warnings"].append("manual_supplement_present")
    return _finalize(updated, registry)
