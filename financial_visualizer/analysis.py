"""Fixed, source-bound financial analysis over the saved SEC snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path
from urllib.parse import urlparse

from scripts.probe_sec import select_fact
from .providers import DEFAULT_CACHE, SEED_ROOT, ReportError
from .issuers import get_issuer

METHOD_VERSION = "analysis-1"

# Distinct concepts are intentionally separate; labels alone do not establish equivalence.
FLOW_TAGS = {
    "research_development": ["ResearchAndDevelopmentExpense"],
    "selling_general_admin": ["SellingGeneralAndAdministrativeExpense"],
    "sales_marketing": ["SellingAndMarketingExpense"],
    "general_admin": ["GeneralAndAdministrativeExpense"],
    "interest_income": ["InvestmentIncomeInterest"],
    "deposit_interest_component": ["InterestIncomeDepositsWithFinancialInstitutions"],
    "interest_expense": ["InterestExpenseNonoperating", "InterestExpense"],
    "nonoperating_income": ["NonoperatingIncomeExpense"],
    "other_nonoperating_income": ["OtherNonoperatingIncomeExpense"],
    "nonoperating_fx_gain_loss": ["ForeignCurrencyTransactionGainLossBeforeTax"],
    "investment_gain": ["GainLossOnInvestments"],
    "equity_method_income": ["IncomeLossFromEquityMethodInvestments"],
    "pretax_before_equity": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "depreciation_amortization": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"],
    "stock_compensation": ["ShareBasedCompensation"],
    "deferred_tax": ["DeferredIncomeTaxExpenseBenefit"],
    "dividends_paid": ["PaymentsOfDividends"],
    "share_repurchases": ["PaymentsForRepurchaseOfCommonStock"],
    "ppe_purchases": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "productive_asset_purchases": ["PaymentsToAcquireProductiveAssets"],
    "business_acquisitions": ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
    "debt_repayments": ["RepaymentsOfDebt"],
    "convertible_debt_repayments": ["RepaymentsOfConvertibleDebt"],
    "debt_proceeds": ["ProceedsFromIssuanceOfDebt", "ProceedsFromDebtNetOfIssuanceCosts"],
    "short_investment_purchases": ["PaymentsToAcquireShortTermInvestments"],
    "short_investment_proceeds": ["ProceedsFromSaleOfShortTermInvestments"],
    "long_investment_purchases": ["PaymentsToAcquireLongtermInvestments"],
    "long_investment_proceeds": ["ProceedsFromSaleOfLongtermInvestments"],
    "debt_security_purchases": ["PaymentsToAcquireAvailableForSaleSecuritiesDebt"],
    "debt_security_sales": ["ProceedsFromSaleOfAvailableForSaleSecuritiesDebt"],
    "debt_security_maturities": ["ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities"],
    "equity_security_purchases": ["PaymentsToAcquireEquitySecuritiesFvNi"],
    "equity_security_sales": ["ProceedsFromSaleOfEquitySecuritiesFvNi"],
    "oci_parent": ["OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent", "OtherComprehensiveIncomeLossNetOfTax"],
    "comprehensive_income_parent": ["ComprehensiveIncomeNetOfTax"],
}
BALANCE_TAGS = {
    "receivables": ["AccountsReceivableNetCurrent"],
    "inventory": ["InventoryNet"],
    "payables": ["AccountsPayableCurrent"],
    "prepaid_assets": ["PrepaidExpenseAndOtherAssetsCurrent"],
    "restricted_cash": ["RestrictedCashCurrent"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "common_stock": ["CommonStockValue"],
    "apic": ["AdditionalPaidInCapital", "AdditionalPaidInCapitalCommonStock"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "aoci": ["AccumulatedOtherComprehensiveIncomeLossNetOfTax"],
    "treasury_stock": ["TreasuryStockValue"],
}
CF_TAGS = {
    "cf_receivables": (["IncreaseDecreaseInAccountsReceivable"], -1, "working_capital"),
    "cf_inventory": (["IncreaseDecreaseInInventories"], -1, "working_capital"),
    "cf_prepaid_assets": (["IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets"], -1, "working_capital"),
    "cf_payables": (["IncreaseDecreaseInAccountsPayable"], 1, "working_capital"),
    "cf_accrued_liabilities": (["IncreaseDecreaseInAccruedLiabilitiesAndOtherOperatingLiabilities"], 1, "working_capital"),
    "cf_other_noncurrent_liabilities": (["IncreaseDecreaseInOtherNoncurrentLiabilities"], 1, "working_capital"),
    "cf_other_noncurrent_assets": (["IncreaseDecreaseInOtherNoncurrentAssets"], -1, "working_capital"),
    "cf_due_from_related": (["IncreaseDecreaseInDueFromRelatedParties"], -1, "working_capital"),
    "cf_due_to_related": (["IncreaseDecreaseInDueToRelatedParties"], 1, "working_capital"),
    "cf_lease_liabilities": (["IncreaseDecreaseInOperatingLeaseLiability"], 1, "working_capital"),
    "cf_other_noncash": (["OtherNoncashIncomeExpense"], -1, "noncash"),
}
ADDITIONAL_BALANCE_TAGS = {
    "unearned_revenue": ["ContractWithCustomerLiability", "DeferredRevenue"],
    "unearned_revenue_current": ["ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent"],
    "unearned_revenue_noncurrent": ["ContractWithCustomerLiabilityNoncurrent", "DeferredRevenueNoncurrent"],
}
ADDITIONAL_FLOW_TAGS = {
    "cf_unearned_revenue": (["IncreaseDecreaseInContractWithCustomerLiability", "IncreaseDecreaseInDeferredRevenue"],
                             {"cashEffectKind": "working_capital", "cashFlowSection": "operating", "isCashFlow": True}),
    "finance_lease_assets_obtained": (["RightOfUseAssetObtainedInExchangeForFinanceLeaseLiability"],
                                     {"cashEffectKind": "noncash", "cashFlowSection": None, "isCashFlow": False}),
    "finance_lease_principal_paid": (["FinanceLeasePrincipalPayments"],
                                    {"cashFlowSection": "financing", "isCashFlow": True}),
    "finance_lease_interest_paid": (["FinanceLeaseInterestPaymentOnLiability"],
                                   {"cashFlowSection": "operating", "isCashFlow": True}),
    "common_stock_dividends_paid": (["PaymentsOfDividendsCommonStock"],
                                    {"cashFlowSection": "financing", "isCashFlow": True}),
}


def amount(fact):
    return Decimal(fact["valueDecimal"]) if fact and fact.get("valueDecimal") is not None else None


def _key_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()[:24]


def _source_data(report, issuer, data_root):
    snapshot = report["snapshot"]
    base_id = snapshot.get("baseId", snapshot["id"])
    directory = SEED_ROOT / "sec" if snapshot["mode"] == "bundled" else Path(data_root or DEFAULT_CACHE) / report["symbol"] / base_id
    path = directory / f"{report['symbol']}-companyfacts.json"
    expected = issuer["acquisition"]["companyfacts"]["sha256"]
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ReportError("snapshot_invalid", "Analysis requires the unchanged selected SEC source snapshot.", 500)
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)["facts"]["us-gaap"]


def _supplements(report, period, issuer_config=None):
    """Load only explicit, period-matched, source-bound disclosure observations."""
    from .core import _fact
    from .providers import ROOT
    path = ROOT / "data" / "analysis" / "2026-11-09" / "disclosure-supplements.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    profile = issuer_config or get_issuer(report["symbol"])
    selections = profile["analysis"]["supplements"]
    sources = {item["id"]: item for item in data.get("sources", [])}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    selected = {}
    for item in data.get("facts", []):
        if item.get("symbol") != report["symbol"] or item.get("start") != period["start"] or item.get("end") != period["end"]:
            continue
        source = sources.get(item.get("sourceId"))
        if not source or source.get("publishedAt", "9999") > report["snapshot"]["asOf"]:
            continue
        if item.get("unit") != "currency" or not any(all(item.get(key) == selection.get(key) for key in ("key", "start", "end", "sourceId")) for selection in selections):
            continue
        if item.get("currency") != report["company"]["currency"] or source.get("currency") != item["currency"] or source.get("periodStart") != item["start"] or source.get("periodEnd") != item["end"]:
            continue
        url = urlparse(source.get("url", ""))
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ReportError("supplement_invalid", "Disclosure supplement source URL is invalid.", 500)
        value = Decimal(item["valueDecimal"])
        if Decimal(item["documentValue"]) * Decimal(source["documentMultiplier"]) != value:
            raise ReportError("supplement_invalid", "Disclosure supplement amount and source multiplier disagree.", 500)
        selected[item["key"]] = _fact(item["key"], {"factId": "ir-observation-" + _key_hash([digest, item]),
                                                    "valueDecimal": str(value), "unit": item["currency"], "start": item["start"], "end": item["end"],
                                                    "source_url": source["url"], "status": "manually_selected", "accession": source.get("accession")}, item["currency"], source["retrievedAt"], "IR_manual",
                                           unit="currency", originalMultiplier=source["documentMultiplier"], originalDocumentValue=item["documentValue"], location=item["location"],
                                           publishedAt=source["publishedAt"], filed=source["publishedAt"], scope=item["scope"],
                                           sourceFile=path.relative_to(ROOT).as_posix(), sourceHash=digest, acquisitionMethod=data["acquisitionMethod"],
                                           disclosureKind=item["kind"], form=source.get("form"), originalDocumentSymbol=item.get("documentSymbol"),
                                           documentInterpretation=item.get("documentInterpretation"))
    return selected


def _derived(report, period, key, value, unit, formula, inputs, **metadata):
    """Create a derived metric only when every declared input exists and is compatible."""
    from .core import format_amount
    if value is None or not inputs or any(fact is None for fact in inputs):
        return None
    if any(fact.get("currency") not in {None, report["company"]["currency"]} for fact in inputs):
        return None
    value = Decimal(value)
    if not value.is_finite():
        return None
    with localcontext() as context:
        context.prec = 64
        rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if unit == "currency":
        display, short = format_amount(value, report["company"]["currency"]), format_amount(value, report["company"]["currency"], True)
    else:
        suffix = report["analysisLocale"]["units"][unit]
        display = short = f"{rounded:.1f}{suffix}"
    refs = [fact["factId"] for fact in inputs]
    identity = _key_hash([METHOD_VERSION, key, period["start"], period["end"], formula, refs, format(value, "f")])
    fact = {"factId": "analysis-" + identity, "key": key, "valueDecimal": format(value, "f"), "unit": unit,
            "displayValue": display, "shortValue": short, "currency": report["company"]["currency"],
            "start": period["start"], "end": period["end"], "source": "calculated", "sourceUrl": None,
            "tag": None, "accession": None, "filed": None, "retrievedAt": report["snapshot"]["retrievedAt"],
            "status": "derived", "rawValue": None, "rawUnit": unit, "sourceMultiplier": None, "documentMultiplier": None,
            "formula": formula, "inputs": refs, "methodVersion": METHOD_VERSION,
            "validation": {"structure": "checked", "calculation": "fixed_formula", "financialReview": "limited", "humanReview": "not_performed"}, **metadata}
    report["facts"].setdefault(fact["factId"], fact)
    return fact


def turnover_days(flow, beginning, ending, days):
    """Use an actual annual day count and two known nonnegative balance anchors."""
    if flow is None or beginning is None or ending is None or days is None or flow <= 0 or beginning < 0 or ending < 0 or days <= 0:
        return None
    return (beginning + ending) / Decimal(2) / flow * Decimal(days)


def _ratio(report, period, key, numerator, denominator, multiplier=100, unit="percent"):
    if not numerator or not denominator or amount(denominator) <= 0:
        return None
    return _derived(report, period, key, amount(numerator) / amount(denominator) * Decimal(multiplier), unit,
                    f"{numerator['key']} / {denominator['key']} * {multiplier}", [numerator, denominator])


def _observation(key, refs=(), params=None, kind="limitation"):
    return {"messageKey": key, "params": params or {}, "refs": [fact["factId"] for fact in refs if fact], "kind": kind}


def augment_report(report, issuer, data_root=None, issuer_config=None, *, prepared_facts=None, include_legacy=True, formation_policies=None):
    """Attach six fixed analysis sections without modifying raw snapshots or old graph values."""
    from .core import LOCALE, _fact, _check
    report["analysisLocale"] = LOCALE["analysis"]
    profile = issuer_config or get_issuer(report["symbol"])
    policy = profile["analysis"]
    raw = _source_data(report, issuer, data_root) if prepared_facts is None else {}
    currency = report["company"]["currency"]
    as_of = report["snapshot"]["asOf"]
    source_facts = {}
    for period in report["periods"]:
        selected = {}
        index = {}
        def put(key, fact):
            selected[key] = fact
            index[key] = fact["factId"] if fact else None
            if fact:
                report["facts"].setdefault(fact["factId"], fact)
            return fact
        def select(key, tags, start, end):
            if prepared_facts is not None:
                return put(key, prepared_facts.get((period["year"], key)))
            data = select_fact(raw, tags, currency, end, start, as_of, issuer["issuer"]["cik"])
            if data.get("accession"):
                candidates = [fact for fact in report["facts"].values() if fact.get("accession") == data["accession"] and fact.get("sourceUrl")]
                data["source_document_url"] = candidates[0]["sourceUrl"] if candidates else None
            fact = _fact(key, data, currency, report["snapshot"]["retrievedAt"], unit="currency",
                         sourceLabel=raw.get(data.get("tag"), {}).get("label"), sourceDescription=raw.get(data.get("tag"), {}).get("description"))
            return put(key, fact)
        for key, tags in FLOW_TAGS.items():
            select(key, tags, period["start"], period["end"])
        for key, tags in BALANCE_TAGS.items():
            select("begin_" + key, tags, None, period["beginningDate"])
            select("end_" + key, tags, None, period["end"])
        for key in policy.get("additionalFacts", []):
            if key in ADDITIONAL_BALANCE_TAGS:
                select("begin_" + key, ADDITIONAL_BALANCE_TAGS[key], None, period["beginningDate"])
                select("end_" + key, ADDITIONAL_BALANCE_TAGS[key], None, period["end"])
            else:
                tags, metadata = ADDITIONAL_FLOW_TAGS[key]
                fact = select(key, tags, period["start"], period["end"])
                if fact:
                    fact.update(metadata)
        if "unearned_revenue" in policy.get("additionalFacts", []):
            for prefix, measurement_date in (("begin_", period["beginningDate"]), ("end_", period["end"])):
                if not selected.get(prefix + "unearned_revenue"):
                    parts = [selected.get(prefix + key) for key in ("unearned_revenue_current", "unearned_revenue_noncurrent")]
                    put(prefix + "unearned_revenue", _derived(report, period, prefix + "unearned_revenue",
                        sum((amount(fact) for fact in parts), Decimal(0)) if all(parts) else None,
                        "currency", "unearned_revenue_current + unearned_revenue_noncurrent", parts,
                        start=None, end=measurement_date))
            put("unearned_revenue", selected.get("end_unearned_revenue"))
        if "common_stock_dividends_paid" in policy.get("additionalFacts", []) and not selected.get("dividends_paid"):
            put("dividends_paid", selected.get("common_stock_dividends_paid"))
        supplements = _supplements(report, period, issuer_config=profile) if include_legacy else {}
        for key in ("acquisition_termination_cost", "cf_acquisition_termination"):
            put(key, supplements.get(key))
        if supplements.get("interest_expense") and not selected["interest_expense"]:
            put("interest_expense", supplements["interest_expense"])
        for key, (tags, sign, kind) in CF_TAGS.items():
            raw_fact = select("raw_" + key, tags, period["start"], period["end"])
            put(key, _derived(report, period, key, amount(raw_fact) * Decimal(sign) if raw_fact else None, "currency",
                              ("-" if sign == -1 else "+") + (raw_fact["tag"] if raw_fact else tags[0]), [raw_fact],
                              cashEffectKind=kind, originalSignRule=sign))
        # An income fact enters the cash view only with an exact-period placement review.
        for rule in policy["cfFromIncome"]:
            key, input_key, sign = rule["key"], rule["inputKey"], rule["sign"]
            review = next((item for item in rule["reviews"] if (item["start"], item["end"]) == (period["start"], period["end"])), None)
            base = selected.get(input_key)
            put(key, _derived(report, period, key, amount(base) * Decimal(sign) if base and review else None, "currency",
                              ("-" if sign == -1 else "+") + input_key, [base], cashEffectKind="noncash",
                              placementReview={field: review[field] for field in ("sourceUrl", "location", "method")} if review else None))
        for rule in policy["cfDirect"]:
            review = next((item for item in rule["reviews"] if (item["start"], item["end"]) == (period["start"], period["end"])), None)
            if not review:
                put(rule["rawKey"], None)
                put(rule["key"], None)
                continue
            base = select(rule["rawKey"], rule["tags"], period["start"], period["end"])
            put(rule["key"], _derived(report, period, rule["key"], amount(base) * Decimal(rule["sign"]) if base else None,
                                      "currency", rule["formula"], [base], cashEffectKind=rule["kind"], contextNote=rule["contextNote"]))
        source_facts[period["year"]] = selected
        period["analysis"] = {"sections": [], "facts": index}
    for i, period in enumerate(report["periods"]):
        facts = source_facts[period["year"]]
        index = period["analysis"]["facts"]
        metrics = period["metrics"]
        def put(key, fact):
            facts[key] = fact
            index[key] = fact["factId"] if fact else None
            return fact
        def row(key):
            fact = facts.get(key) or metrics.get(key)
            if key not in index:
                index[key] = fact["factId"] if fact else None
            return {"key": key, "labelKey": key, "factId": fact["factId"] if fact else None}
        def section(identity, keys, observations, missing=(), checks=(), status="partial"):
            rows = [row(key) for key in keys]
            required = [entry["key"] for entry in rows if entry["factId"] is None]
            result = {"id": identity, "titleKey": "analysis_" + identity, "status": status if any(entry["factId"] for entry in rows) else "unavailable",
                      "rows": rows, "observations": observations, "missing": list(dict.fromkeys([*missing, *required])), "checks": list(checks)}
            period["analysis"]["sections"].append(result)
            return result
        for key, numerator in (("research_ratio", facts["research_development"]), ("sga_ratio", facts["selling_general_admin"]), ("marketing_ratio", facts["sales_marketing"])):
            put(key, _ratio(report, period, key, numerator, metrics["revenue"]))
        put("effective_tax_rate", _ratio(report, period, "effective_tax_rate", metrics["income_tax"], metrics["pretax_income"]))
        profit_checks = []
        if facts["selling_general_admin"]:
            expense_inputs = [facts["research_development"], facts["selling_general_admin"]]
        else:
            expense_inputs = [facts["research_development"], facts["sales_marketing"], facts["general_admin"]]
        if facts["acquisition_termination_cost"]:
            expense_inputs.append(facts["acquisition_termination_cost"])
        expense_sum = sum((amount(fact) for fact in expense_inputs), Decimal(0)) if all(expense_inputs) else None
        profit_checks.append(_check("disclosed_expense_components_vs_total", expense_sum, amount(metrics["operating_expenses"]), [fact["factId"] for fact in expense_inputs if fact]))
        if facts["equity_method_income"] and facts["pretax_before_equity"]:
            profit_checks.append(_check("pretax_equity_method_scope", amount(facts["pretax_before_equity"]) + amount(facts["equity_method_income"]), amount(metrics["pretax_income"]),
                                       [fact["factId"] for fact in (facts["pretax_before_equity"], facts["equity_method_income"], metrics["pretax_income"]) if fact]))
        change_keys = []
        if i:
            previous = report["periods"][i - 1]
            for key, metric, sign in (("revenue_change_effect", "revenue", 1), ("cost_change_effect", "cost_of_revenue", -1),
                                      ("expense_change_effect", "operating_expenses", -1), ("operating_profit_change", "operating_income", 1),
                                      ("net_profit_change", "net_income", 1)):
                current, before = metrics[metric], previous["metrics"][metric]
                value = (amount(current) - amount(before)) * Decimal(sign) if current and before else None
                put(key, _derived(report, period, key, value, "currency", f"{sign} * (current_{metric} - previous_{metric})", [current, before],
                                  comparisonFromYear=previous["year"], comparisonToYear=period["year"], interpretation="Arithmetic contribution, not independent economic causality."))
                change_keys.append(key)
            effects = [facts.get(key) for key in ("revenue_change_effect", "cost_change_effect", "expense_change_effect")]
            profit_checks.append(_check("operating_profit_change_decomposition", sum((amount(fact) for fact in effects), Decimal(0)) if all(effects) else None,
                                       amount(facts.get("operating_profit_change")), [fact["factId"] for fact in effects if fact]))
        expense_keys = ["research_development", "selling_general_admin", "research_ratio", "sga_ratio"] if facts["selling_general_admin"] else ["research_development", "sales_marketing", "general_admin", "research_ratio", "marketing_ratio"]
        if facts["acquisition_termination_cost"]:
            expense_keys.append("acquisition_termination_cost")
        optional_profit = [key for key in ("interest_income", "interest_expense", "nonoperating_income", "other_nonoperating_income", "equity_method_income", "pretax_before_equity") if facts.get(key)]
        scope_refs = [facts["pretax_before_equity"], facts["equity_method_income"]] if policy["formation"]["afterTaxKeys"] else []
        profit_notes = [_observation("parent_child_no_double_count", [facts["interest_income"], facts["deposit_interest_component"]])]
        if policy["notes"]["profitScope"]:
            profit_notes.append(_observation(policy["notes"]["profitScope"], scope_refs))
        if i and all(facts.get(key) for key in ("revenue_change_effect", "cost_change_effect", "expense_change_effect", "operating_profit_change")):
            refs = [facts[key] for key in ("revenue_change_effect", "cost_change_effect", "expense_change_effect", "operating_profit_change")]
            profit_notes.insert(0, _observation("operating_change_observed", refs,
                                               {"fromYear": str(report["periods"][i - 1]["year"]), "toYear": str(period["year"]),
                                                "revenueDelta": refs[0]["shortValue"], "costEffect": refs[1]["shortValue"], "expenseEffect": refs[2]["shortValue"], "operatingDelta": refs[3]["shortValue"]}, "calculation"))
        expense_partial = profit_checks[0]["status"] != "match"
        if expense_partial:
            profit_notes.append(_observation("expense_components_incomplete", expense_inputs))
        profit_section = section("profit", ["revenue", "gross_profit", "operating_income", *expense_keys, *optional_profit, "pretax_income", "income_tax", "effective_tax_rate", "net_income", *change_keys],
                                 profit_notes, missing=["temporary_item_classification", *(["complete_expense_components"] if expense_partial else [])], checks=profit_checks)
        profit_section["chart"] = None
        if i:
            before = report["periods"][i - 1]["metrics"].get("operating_income")
            current = metrics.get("operating_income")
            effects = [facts.get(key) for key in ("revenue_change_effect", "cost_change_effect", "expense_change_effect")]
            if before and current and all(effects) and amount(before) + sum((amount(fact) for fact in effects), Decimal(0)) == amount(current):
                steps = [{"key": "previous_operating_income", "kind": "total", "factId": before["factId"], "startDecimal": "0", "endDecimal": before["valueDecimal"], "displayValue": before["shortValue"]}]
                cursor = amount(before)
                for fact in effects:
                    endpoint = cursor + amount(fact)
                    steps.append({"key": fact["key"], "kind": "flow", "factId": fact["factId"], "startDecimal": format(cursor, "f"), "endDecimal": format(endpoint, "f"), "displayValue": fact["shortValue"]})
                    cursor = endpoint
                steps.append({"key": "operating_income", "kind": "total", "factId": current["factId"], "startDecimal": "0", "endDecimal": current["valueDecimal"], "displayValue": current["shortValue"]})
                profit_section["chart"] = {"type": "profit_bridge", "fromYear": report["periods"][i - 1]["year"], "toYear": period["year"], "steps": steps}

        # Only disclosed nonoperating concepts enter this bridge; no pretax residual is a fact.
        for key, source_key in (("income_tax_effect", "income_tax"), ("interest_expense_effect", "interest_expense")):
            source = metrics.get(source_key) if source_key == "income_tax" else facts.get(source_key)
            put(key, _derived(report, period, key, -amount(source) if source else None, "currency", "-" + source_key, [source]))
        formation_policy = (formation_policies or {}).get(period["year"], policy["formation"])
        nonoperating_keys = formation_policy["nonoperatingKeys"]
        pretax_target = metrics.get(formation_policy["pretaxKey"]) or facts.get(formation_policy["pretaxKey"])
        complete_nonoperating = formation_policy["mode"] != "unavailable" and bool(nonoperating_keys) and all(facts.get(key) for key in nonoperating_keys)
        operating = metrics.get("operating_income")
        disclosed_flows = [facts[key] for key in nonoperating_keys if facts.get(key)]
        pretax_sum = amount(operating) + sum((amount(fact) for fact in disclosed_flows), Decimal(0)) if operating and disclosed_flows else None
        formation_check = _check("disclosed_nonoperating_to_pretax", pretax_sum, amount(pretax_target), [fact["factId"] for fact in ([operating, *disclosed_flows, pretax_target]) if fact])
        profit_section["checks"].append(formation_check)
        formation_flows = [*disclosed_flows, facts.get("income_tax_effect")]
        formation_flows.extend(facts.get(key) for key in formation_policy["afterTaxKeys"])
        profit_section["formationChart"] = None
        final_income = metrics.get("net_income")
        if complete_nonoperating and operating and final_income and formation_flows and all(formation_flows) and formation_check["status"] == "match":
            endpoint = amount(operating) + sum((amount(fact) for fact in formation_flows), Decimal(0))
            if endpoint == amount(final_income):
                steps = [{"key": "operating_income", "kind": "total", "factId": operating["factId"], "startDecimal": "0", "endDecimal": operating["valueDecimal"], "displayValue": operating["shortValue"]}]
                cursor = amount(operating)
                for flow_index, fact in enumerate(formation_flows):
                    next_cursor = cursor + amount(fact)
                    steps.append({"key": fact["key"], "kind": "flow", "factId": fact["factId"], "startDecimal": format(cursor, "f"), "endDecimal": format(next_cursor, "f"), "displayValue": fact["shortValue"]})
                    cursor = next_cursor
                    if flow_index == len(disclosed_flows) - 1:
                        steps.append({"key": pretax_target["key"], "kind": "total", "factId": pretax_target["factId"], "startDecimal": "0", "endDecimal": pretax_target["valueDecimal"], "displayValue": pretax_target["shortValue"]})
                steps.append({"key": "net_income", "kind": "total", "factId": final_income["factId"], "startDecimal": "0", "endDecimal": final_income["valueDecimal"], "displayValue": final_income["shortValue"]})
                profit_section["formationChart"] = {"type": "income_formation", "status": "eligible" if complete_nonoperating else "partial", "steps": steps,
                                                     "nonoperatingMode": formation_policy["mode"],
                                                     "scope": "consolidated", "missing": [] if complete_nonoperating else [key for key in nonoperating_keys if not facts.get(key)]}
        if formation_policy["observationKey"]:
            profit_section["observations"].append(_observation(formation_policy["observationKey"], [*disclosed_flows, pretax_target], kind="fact"))
        if not complete_nonoperating or profit_section["formationChart"] is None:
            profit_section["observations"].append(_observation("income_formation_incomplete", [operating, *disclosed_flows, final_income]))

        # Use only disclosed cashflow movements, never balance differences.
        cash_adjustments = [("net_income", metrics["net_income"], "profit"), ("stock_compensation", facts["stock_compensation"], "noncash"),
                            ("depreciation_amortization", facts["depreciation_amortization"], "noncash"), ("deferred_tax", facts["deferred_tax"], "noncash")]
        cash_adjustments += [(key, facts.get(key), kind) for key, (_, _, kind) in CF_TAGS.items()]
        cash_adjustments += [(key, facts.get(key), "noncash") for key in ("cf_investment_gain", "cf_equity_method", "cf_interest_investment_adjustment")]
        if facts["cf_acquisition_termination"]:
            cash_adjustments.append(("cf_acquisition_termination", facts["cf_acquisition_termination"], "noncash"))
        items = []
        for key, fact, kind in cash_adjustments:
            if fact:
                copied = dict(fact, nameKey=key, kind=kind)
                items.append(copied)
        if period["reconciliation"]["status"] != "eligible" and not period["reconciliation"].get("review"):
            period["reconciliation"]["items"] = items
            period["reconciliation"]["steps"] = []
            total = sum((amount(item) for item in items), Decimal(0))
            check = _check("known_cfo_items_diagnostic", total if metrics["net_income"] else None, amount(metrics["cfo"]), [item["factId"] for item in items])
            check["scope"] = "partial_input_set_diagnostic; a zero residual alone cannot establish complete source coverage"
            period["reconciliation"]["check"] = check
            period["reconciliation"]["missing"] = ["complete_operating_adjustments", "cashflow_table_placement_and_sign_review"]
        put("cash_minus_profit", _derived(report, period, "cash_minus_profit", amount(metrics["cfo"]) - amount(metrics["net_income"]) if metrics["cfo"] and metrics["net_income"] else None,
                                           "currency", "cfo - net_income", [metrics["cfo"], metrics["net_income"]], interpretation="Diagnostic comparison only; never an added CFO adjustment."))
        cash_keys = [key for key, fact, _ in cash_adjustments if fact] + ["cfo"]
        if period["reconciliation"]["status"] == "eligible":
            cash_keys = []
            for item in period["reconciliation"]["items"]:
                key = "ir_" + item["nameKey"]
                put(key, item)
                cash_keys.append(key)
            cash_keys.append("cfo")
        cash_notes = [_observation("cf_movements_are_not_balance_changes", [facts.get("cf_receivables"), facts.get("cf_inventory"), facts.get("cf_payables")], kind="fact"),
                      _observation("sbc_addback_not_free", [facts["stock_compensation"]])]
        if policy["notes"]["cashConversion"]:
            cash_notes.append(_observation(policy["notes"]["cashConversion"]))
        if facts["cash_minus_profit"]:
            cash_notes.insert(0, _observation("cash_profit_observed", [metrics["net_income"], metrics["cfo"], facts["cash_minus_profit"]],
                                             {"profit": metrics["net_income"]["shortValue"], "cfo": metrics["cfo"]["shortValue"], "gap": facts["cash_minus_profit"]["shortValue"]}, "calculation"))
        section("cash_conversion", cash_keys,
                cash_notes,
                missing=[] if period["reconciliation"]["status"] == "eligible" else ["complete_operating_adjustments"],
                checks=[period["reconciliation"]["check"]] if period["reconciliation"].get("check") else [], status=period["reconciliation"]["status"])

        working_keys = []
        working_balances = ["receivables", "inventory", "payables"]
        if "unearned_revenue" in policy.get("additionalFacts", []):
            working_balances.append("unearned_revenue")
        for key in working_balances:
            begin, end = facts["begin_" + key], facts["end_" + key]
            change_key = key + "_balance_change"
            put(change_key, _derived(report, period, change_key, amount(end) - amount(begin) if end and begin else None, "currency",
                                    f"end_{key} - begin_{key}", [end, begin], interpretation="Balance movement only; not a cashflow fact."))
            working_keys += ["begin_" + key, "end_" + key, change_key, "cf_" + key]
        days = (date.fromisoformat(period["end"]) - date.fromisoformat(period["start"])).days + 1 if period["end"] and period["start"] else None
        period["analysis"]["fiscalDays"] = days
        efficiency_keys = ["effective_tax_rate", "research_ratio", "marketing_ratio"]
        for rule in policy["turnover"]:
            key, balance_key, denominator_key = rule["key"], rule["balanceKey"], rule["denominatorKey"]
            begin, end, flow = facts.get("begin_" + balance_key), facts.get("end_" + balance_key), metrics.get(denominator_key)
            value = turnover_days(amount(flow), amount(begin), amount(end), days)
            put(key, _derived(report, period, key, value, "days", f"((begin_{balance_key} + end_{balance_key}) / 2) / {denominator_key} * {days}", [begin, end, flow],
                              fiscalDays=days, approximation=rule["approximation"]))
            efficiency_keys.append(key)
        assets_begin, assets_end = metrics.get("begin_assets"), metrics.get("assets")
        average_assets = (amount(assets_begin) + amount(assets_end)) / Decimal(2) if assets_begin and assets_end else None
        put("total_asset_turnover", _derived(report, period, "total_asset_turnover", amount(metrics["revenue"]) / average_assets if metrics["revenue"] and average_assets is not None and average_assets > 0 else None,
                                            "times", "revenue / ((begin_assets + end_assets) / 2)", [metrics["revenue"], assets_begin, assets_end]))
        efficiency_keys.append("total_asset_turnover")
        working_notes = [_observation("balance_change_not_cash_effect", kind="fact")]
        if policy["notes"]["workingCapital"]:
            working_notes.append(_observation(policy["notes"]["workingCapital"]))
        for key in ("receivables", "inventory"):
            change, cash = facts.get(key + "_balance_change"), facts.get("cf_" + key)
            label = report["analysisLocale"]["labels"]["end_" + key]
            if change and cash:
                working_notes.insert(0, _observation("working_movement_observed", [change, cash], {"item": label, "balanceChange": change["shortValue"], "cashEffect": cash["shortValue"]}, "calculation"))
            elif change:
                working_notes.insert(0, _observation("working_cash_missing", [change], {"item": label, "balanceChange": change["shortValue"]}, "calculation"))
        section("working_capital", [*working_keys, "end_restricted_cash", "end_prepaid_assets", "cf_prepaid_assets"], working_notes,
                missing=[policy["notes"]["workingMissing"]] if policy["notes"]["workingMissing"] else [])
        section("efficiency", efficiency_keys,
                [_observation("actual_days_average_balances", params={"days": str(days)}, kind="fact"),
                 _observation("asset_turnover_is_not_noa_turnover"), _observation("noa_rnoa_unavailable")], missing=["noa", "after_tax_operating_profit", "rnoa"])

        purchase = facts.get(policy["assetPurchaseKey"])
        put("cash_after_defined_asset_purchases", _derived(report, period, "cash_after_defined_asset_purchases", amount(metrics["cfo"]) - amount(purchase) if metrics["cfo"] and purchase else None,
                                                          "currency", "cfo - defined_asset_purchases", [metrics["cfo"], purchase], definition="Simplified cash indicator, not company-reported FCF or distributable cash."))
        cash_use_keys = ["productive_asset_purchases", "ppe_purchases", "business_acquisitions", "short_investment_purchases", "short_investment_proceeds", "long_investment_purchases",
                         "long_investment_proceeds", "debt_security_purchases", "debt_security_sales", "debt_security_maturities", "equity_security_purchases", "equity_security_sales",
                         "debt_proceeds", "debt_repayments", "convertible_debt_repayments", "dividends_paid", "share_repurchases", "cash_after_defined_asset_purchases"]
        cash_use_keys = [key for key in cash_use_keys if facts.get(key)]
        cash_use_keys.extend(key for key in ("finance_lease_principal_paid", "finance_lease_interest_paid", "finance_lease_assets_obtained")
                             if key in policy.get("additionalFacts", []))
        if not purchase:
            cash_use_keys.append("ppe_purchases")
        cash_use_section = section("cash_uses", cash_use_keys, [_observation("investments_are_not_capex"), _observation("cash_uses_may_overlap_do_not_sum"), _observation("simplified_cash_not_company_fcf", [purchase])],
                                   missing=["complete_investing_financing_mapping", "maintenance_growth_capex_split"])
        if "finance_lease_assets_obtained" in policy.get("additionalFacts", []):
            cash_use_section["observations"].append(_observation("finance_lease_addition_is_noncash",
                [facts.get("finance_lease_assets_obtained"), facts.get("finance_lease_principal_paid"), facts.get("finance_lease_interest_paid")], kind="fact"))
        put("begin_equity", metrics.get("begin_equity"))
        put("end_equity", metrics.get("equity"))
        equity_rows = []
        for key, relation in [("begin_equity", "balance"), ("end_equity", "balance"), ("net_income", "profit"), ("oci_parent", "oci"),
                              ("comprehensive_income_parent", "oci"), ("dividends_paid", "owner_cash"), ("share_repurchases", "owner_cash"), ("stock_compensation", "expense")]:
            equity_rows.append({**row(key), "relation": relation})
        for component in ("common_stock", "apic", "retained_earnings", "aoci", "treasury_stock"):
            if facts.get("begin_" + component) or facts.get("end_" + component):
                equity_rows.extend({**row(key), "relation": "balance"} for key in ("begin_" + component, "end_" + component))
        cash_use_section["equityChart"] = {"type": "equity_components", "status": "partial", "beginFactId": index["begin_equity"], "endFactId": index["end_equity"],
                                           "rows": equity_rows, "missing": ["complete_equity_movements", "equity_transaction_vs_cash_reconciliation"],
                                           "scope": "parent_equity", "bridgeAvailable": False}
        cash_use_section["observations"].append(_observation("equity_components_are_not_a_bridge", [metrics.get("begin_equity"), metrics.get("equity"), facts.get("oci_parent")], kind="fact"))
        cash_use_section["observations"].append(_observation("equity_cash_and_sbc_not_equity_movements", [facts.get("stock_compensation"), facts.get("share_repurchases"), facts.get("dividends_paid")]))
        put("cash_minus_profit", _derived(report, period, "cash_minus_profit", amount(metrics["cfo"]) - amount(metrics["net_income"]) if metrics["cfo"] and metrics["net_income"] else None,
                                           "currency", "cfo - net_income", [metrics["cfo"], metrics["net_income"]], interpretation="Diagnostic comparison only; never an added CFO adjustment."))
        put("cash_profit_conversion", _ratio(report, period, "cash_profit_conversion", metrics["cfo"], metrics["net_income"]))
        put("sbc_revenue_ratio", _ratio(report, period, "sbc_revenue_ratio", facts["stock_compensation"], metrics["revenue"]))
        quality_observations = [_observation("cfo_above_profit_is_not_quality_score", [metrics["cfo"], metrics["net_income"]]),
                                _observation("sbc_addback_not_free", [facts["stock_compensation"]]), _observation("reported_nonoperating_not_automatically_temporary")]
        if policy["notes"]["quality"]:
            quality_observations.append(_observation(policy["notes"]["quality"], [facts["end_restricted_cash"], metrics["cash_end"]]))
        section("quality", ["cash_minus_profit", "cash_profit_conversion", "stock_compensation", "sbc_revenue_ratio", "effective_tax_rate", "end_restricted_cash"],
                quality_observations, missing=["temporary_item_classification", "footnote_judgment"])
    from .cash_analysis import attach_cash_research
    from .providers import ROOT
    cash_profile_path = ROOT / policy["cashProfileFile"] if policy.get("cashProfileFile") else None
    if include_legacy:
        report = attach_cash_research(report, issuer, raw, path=cash_profile_path)
    # A reviewed source alias keeps the same explicitly enabled relation type.
    for period in report["periods"]:
        for key in policy.get("additionalFacts", []):
            identity = period["analysis"]["facts"].get(key)
            if key in ADDITIONAL_FLOW_TAGS and identity:
                report["facts"][identity].update(ADDITIONAL_FLOW_TAGS[key][1])
    return report
