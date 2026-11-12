"""Source-bound cash research configured by reviewed disclosure profiles.

The arithmetic functions do not know issuer names or fiscal years.  Profiles
describe a reviewed statement's complete row set; arithmetic equality alone
never establishes completeness, merchant ownership, or spendable cash.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, localcontext
from pathlib import Path
from urllib.parse import urlparse

from .providers import ROOT, ReportError

METHOD_VERSION = "cash-research-1"
PROFILE_PATH = Path("data/analysis/2026-11-09/cash-profiles.json")
GROUPS = ("noncash", "operating_assets", "settlement_liabilities", "other_operating_liabilities")


def _decimal(value):
    from .core import _decimal as parse
    if not isinstance(value, str):
        raise ReportError("cash_profile_invalid", "Cash research amounts must be decimal strings.", 500)
    return parse(value)


def _text(value):
    return format(value, "f")


def _url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password


def _compatible(fact, *, start, end, currency, scope):
    return bool(fact and fact.get("start") == start and fact.get("end") == end
                and fact.get("currency") == currency and fact.get("scope") == scope
                and fact.get("unit", "currency") == "currency"
                and isinstance(fact.get("valueDecimal"), str))


def _source_identity(fact):
    """Identify reviewed aliases by the native fact they represent."""
    if fact.get("equivalentFactId"):
        return fact["equivalentFactId"]
    if fact.get("cashResearchMethod") == METHOD_VERSION and fact.get("disclosureKind") == "cash_flow_adjustment" and len(fact.get("inputs", [])) == 1:
        return fact["inputs"][0]
    return fact.get("factId")


def _check(name, left, right, inputs):
    from .core import _check as check
    return check(name, left, right, inputs, "reviewed_cash_profile; arithmetic_not_ownership_or_availability")


def evaluate_bridge(net_income, cfo, rows, *, start, end, currency, scope,
                    complete=False, source_review=None):
    """Validate a declared adjustment set independently of profile loading.

    Missing rows remain missing even when known rows happen to sum to CFO.
    Invalid period, currency, scope, repeated identities and unsupported groups
    produce a conflict.  A residual is a diagnostic and never a new row.
    """
    missing, conflicts, known, keys, identities = [], [], [], set(), set()
    for key, fact in (("net_income", net_income), ("cfo", cfo)):
        if not fact:
            missing.append(key)
        elif not _compatible(fact, start=start, end=end, currency=currency, scope=scope):
            conflicts.append(key + "_incompatible")
    for row in rows:
        key, fact = row.get("key"), row.get("fact")
        if not isinstance(key, str) or key in keys or row.get("group") not in GROUPS:
            conflicts.append("invalid_or_duplicate_adjustment")
        keys.add(key)
        if fact is None:
            missing.append(key or "adjustment")
            continue
        if not _compatible(fact, start=start, end=end, currency=currency, scope=scope):
            conflicts.append(str(key) + "_incompatible")
            continue
        if fact.get("disclosureKind") != "cash_flow_adjustment":
            conflicts.append(str(key) + "_cashflow_context_unreviewed")
            continue
        identity = _source_identity(fact)
        if not isinstance(identity, str) or identity in identities or identity in {_source_identity(item) for item in (net_income, cfo) if item}:
            conflicts.append("duplicate_adjustment_identity")
        identities.add(identity)
        known.append(row)
    review = source_review or {}
    reviewed = _url(review.get("url")) and isinstance(review.get("location"), str) and bool(review["location"].strip())
    if complete is not True:
        missing.append("complete_operating_adjustments")
    if not reviewed:
        missing.append("cashflow_table_placement_and_sign_review")
    inputs = [net_income["factId"]] if net_income else []
    inputs += [row["fact"]["factId"] for row in known]
    if cfo:
        inputs.append(cfo["factId"])
    with localcontext() as context:
        context.prec = 64
        total = _decimal(net_income["valueDecimal"]) + sum((_decimal(row["fact"]["valueDecimal"]) for row in known), Decimal(0)) if net_income and not conflicts else None
        check = _check("reviewed_adjustments_equal_cfo", total,
                       _decimal(cfo["valueDecimal"]) if cfo and not conflicts else None, inputs)
    status = "conflict" if conflicts or (not missing and check["status"] == "mismatch") else "partial" if missing else "eligible"
    return {"status": status, "missing": list(dict.fromkeys(missing)), "conflicts": list(dict.fromkeys(conflicts)),
            "check": check, "rows": known, "sourceReview": review, "coverageDeclaredComplete": complete is True}


def evaluate_cash_scope(cash, restricted, total, *, date, currency, scope):
    """Reconcile cash definitions at one date without netting liabilities."""
    values = {"cash": cash, "restricted": restricted, "total": total}
    missing = [key for key, fact in values.items() if fact is None]
    conflicts = [key for key, fact in values.items() if fact and not _compatible(fact, start=None, end=date, currency=currency, scope=scope)]
    known = [fact for fact in values.values() if fact]
    with localcontext() as context:
        context.prec = 64
        left = _decimal(cash["valueDecimal"]) + _decimal(restricted["valueDecimal"]) if not missing and not conflicts else None
        right = _decimal(total["valueDecimal"]) if total and not conflicts else None
    check = _check("cash_plus_restricted_equals_cashflow_cash", left, right, [fact["factId"] for fact in known])
    if any(_decimal(fact["valueDecimal"]) < 0 for fact in known):
        conflicts.append("negative_cash_component")
    status = "conflict" if conflicts or check["status"] == "mismatch" else "partial" if missing else "eligible"
    return {"status": status, "missing": missing, "conflicts": conflicts, "check": check,
            **{key + "FactId": fact["factId"] if fact else None for key, fact in values.items()}}


def _derived(report, period, key, value, inputs, formula, *, unit="currency", **extra):
    from .analysis import _derived as derive
    return derive(report, period, key, value, unit, formula, inputs,
                  scope=extra.pop("scope", "consolidated"), cashResearchMethod=METHOD_VERSION, **extra)


def _steps(net_income, cfo, entries):
    if not net_income or not cfo:
        return []
    cursor = _decimal(net_income["valueDecimal"])
    result = [{"key": "net_income", "kind": "total", "factId": net_income["factId"],
               "startDecimal": "0", "endDecimal": _text(cursor), "displayValue": net_income["shortValue"]}]
    with localcontext() as context:
        context.prec = 64
        for entry in entries:
            fact = entry["fact"]
            following = cursor + _decimal(fact["valueDecimal"])
            result.append({"key": entry["key"], "kind": "flow", "factId": fact["factId"],
                           "startDecimal": _text(cursor), "endDecimal": _text(following), "displayValue": fact["shortValue"]})
            cursor = following
    result.append({"key": "cfo", "kind": "total", "factId": cfo["factId"],
                   "startDecimal": "0", "endDecimal": cfo["valueDecimal"], "displayValue": cfo["shortValue"]})
    return result


def _load_observations(report, profile, data, digest, raw, issuer, source_file):
    from .core import _fact
    from scripts.probe_sec import select_fact
    source_list = data.get("sources", [])
    observation_list = data.get("observations", [])
    sources = {source["id"]: source for source in source_list}
    if len(sources) != len(source_list) or len({item["id"] for item in observation_list}) != len(observation_list):
        raise ReportError("cash_profile_invalid", "Cash disclosure identities must be unique.", 500)
    facts, conflicts = {}, []
    available = {item["id"] for item in observation_list}
    references = set()
    def collect(value):
        if isinstance(value, str) and value in available:
            references.add(value)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, dict):
            for child in value.values():
                collect(child)
    collect(profile)
    reviewed_documents = {}
    for item in data.get("observations", []):
        if item.get("id") not in references:
            continue
        source = sources.get(item.get("sourceId"))
        if not source or source.get("publishedAt", "9999") > report["snapshot"]["asOf"]:
            continue
        if not _url(source.get("url")) or not source.get("retrievedAt") or not item.get("location"):
            raise ReportError("cash_profile_invalid", "Cash disclosure provenance is incomplete.", 500)
        if source.get("documentFile") or source.get("documentSha256"):
            if source["id"] not in reviewed_documents:
                name, expected_hash = source.get("documentFile"), source.get("documentSha256")
                if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts or not isinstance(expected_hash, str):
                    raise ReportError("cash_profile_invalid", "Original disclosure document reference is invalid.", 500)
                document = (ROOT / name).resolve()
                if not document.is_relative_to(ROOT.resolve()) or not document.is_file() or hashlib.sha256(document.read_bytes()).hexdigest() != expected_hash:
                    raise ReportError("cash_profile_invalid", "Original disclosure document integrity could not be verified.", 500)
                reviewed_documents[source["id"]] = {"documentFile": name, "documentSha256": expected_hash}
        if item.get("symbol") != report["symbol"] or item.get("currency") != profile["currency"] or source.get("currency") != profile["currency"] or item.get("scope") != profile["scope"]:
            conflicts.append(item["id"] + "_incompatible")
            continue
        document_value, multiplier = _decimal(item["documentValue"]), _decimal(source["documentMultiplier"])
        value = _decimal(item["valueDecimal"])
        with localcontext() as context:
            context.prec = 64
            document_amount = document_value * multiplier
        if multiplier <= 0 or document_amount != value:
            raise ReportError("cash_profile_invalid", "Cash disclosure amount and multiplier disagree.", 500)
        evidence = {"sourceId": source["id"], "url": source["url"], "location": item["location"],
                    "documentValue": item["documentValue"], "documentMultiplier": source["documentMultiplier"],
                    "sourceFile": source_file, "sourceHash": digest,
                    "publishedAt": source["publishedAt"], "retrievedAt": source["retrievedAt"]}
        evidence.update(reviewed_documents.get(source["id"], {}))
        observation = _fact(item["key"], {"factId": "cash-observation-" + hashlib.sha256((digest + item["id"]).encode()).hexdigest()[:24],
                                        "valueDecimal": item["valueDecimal"], "start": item.get("start"), "end": item["end"],
                                        "unit": item["currency"], "entity_scope": item["scope"], "source_url": source["url"],
                                        "status": "manually_selected", "accession": source.get("accession")},
                            item["currency"], source["retrievedAt"], "IR_manual", unit="currency",
                            originalMultiplier=source["documentMultiplier"], location=item["location"],
                            publishedAt=source["publishedAt"], filed=source["publishedAt"],
                            sourceFile=source_file, sourceHash=digest, documentReview=evidence,
                            disclosureKind=item.get("context"), cashDefinition=item.get("cashDefinition"),
                            form=source.get("form"), originalDocumentSymbol=item.get("documentSymbol"))
        fact = observation
        tag = item.get("tag")
        if tag:
            selection = select_fact(raw, [tag], item["currency"], item["end"], item.get("start"), report["snapshot"]["asOf"], issuer["issuer"]["cik"])
            if selection.get("valueDecimal") is not None:
                sign = _decimal(str(item.get("tagSign", "1")))
                if sign not in {Decimal(-1), Decimal(1)}:
                    raise ReportError("cash_profile_invalid", "Cash tag sign must be one or minus one.", 500)
                selection["source_document_url"] = source["url"] if selection.get("accession") == source.get("accession") else None
                native = _fact(item["key"], selection, item["currency"], report["snapshot"]["retrievedAt"], unit="currency")
                report["facts"].setdefault(native["factId"], native)
                native_value = _decimal(native["valueDecimal"])
                signed_value = native_value if sign == 1 else native_value.copy_negate()
                if signed_value != value:
                    conflicts.append(item["id"] + "_source_value_difference")
                    observation["documentReview"]["structuredValueConflictFactId"] = native["factId"]
                elif sign == 1:
                    fact = dict(native, factId="cash-reviewed-" + hashlib.sha256((digest + item["id"]).encode()).hexdigest()[:24],
                                key=item["key"], documentReview=evidence, disclosureKind=item.get("context"),
                                cashDefinition=item.get("cashDefinition"), sourceEntityScope=native["scope"], scope=item["scope"],
                                equivalentFactId=native["factId"])
                else:
                    fact = _derived(report, profile, item["key"], value, [native],
                                    "-" + tag + " (reviewed cashflow table sign)", scope=item["scope"],
                                    documentReview=evidence, cashEffectKind="reviewed_cashflow_adjustment",
                                    disclosureKind=item.get("context"))
        report["facts"].setdefault(fact["factId"], fact)
        facts[item["id"]] = fact
    return facts, sources, conflicts


def attach_cash_research(report, issuer, raw, *, path=None):
    """Attach profiles matching exact issuer/period/currency to an existing report."""
    path = Path(path) if path else ROOT / PROFILE_PATH
    if not path.exists():
        return report
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != "1.0":
        raise ReportError("cash_profile_invalid", "Unsupported cash disclosure profile schema.", 500)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    resolved_path = path.resolve()
    source_file = resolved_path.relative_to(ROOT.resolve()).as_posix() if resolved_path.is_relative_to(ROOT.resolve()) else str(resolved_path)
    for period in report["periods"]:
        candidates = [profile for profile in data.get("profiles", []) if profile.get("symbol") == report["symbol"]
                      and (profile.get("start"), profile.get("end")) == (period["start"], period["end"])]
        if not candidates:
            continue
        if len(candidates) != 1:
            raise ReportError("cash_profile_invalid", "Duplicate annual cash profiles.", 500)
        profile = candidates[0]
        if profile.get("currency") != report["company"]["currency"] or profile.get("scope") != "consolidated":
            raise ReportError("cash_profile_invalid", "Cash profile currency or entity scope is incompatible.", 500)
        observations, sources, observation_conflicts = _load_observations(report, profile, data, digest, raw, issuer, source_file)
        def get(identity):
            return observations.get(identity) if identity else None
        def register(fact):
            if fact:
                report["facts"].setdefault(fact["factId"], fact)
                period["analysis"]["facts"][fact["key"]] = fact["factId"]
            return fact
        for fact in observations.values():
            register(fact)
        definition = profile.get("bridge", {})
        source_review = definition.get("review", {})
        source = sources.get(source_review.get("sourceId"), {})
        review_available = source.get("publishedAt", "9999") <= report["snapshot"]["asOf"]
        review = {**source_review, "url": source.get("url") if review_available else None, "publishedAt": source.get("publishedAt"),
                  "sourceHash": digest, "method": "Explicit reviewed disclosure row set; not inferred from arithmetic closure."}
        rows = [{**row, "fact": get(row.get("observationId"))} for row in definition.get("rows", [])]
        metric_net_income, metric_cfo = period["metrics"].get("net_income"), period["metrics"].get("cfo")
        net_income = get(definition.get("netIncome")) or metric_net_income
        cfo = get(definition.get("cfo")) or metric_cfo
        result = evaluate_bridge(net_income, cfo, rows, start=period["start"], end=period["end"],
                                 currency=profile["currency"], scope=profile["scope"],
                                 complete=definition.get("complete") is True, source_review=review)
        for key, metric in (("netIncome", metric_net_income), ("cfo", metric_cfo)):
            identity = definition.get(key)
            if identity:
                disclosed = get(identity)
                if not disclosed:
                    result["missing"].append(key + "_disclosure_endpoint")
                elif not metric:
                    result["missing"].append(key + "_metric_endpoint")
                elif _decimal(disclosed["valueDecimal"]) != _decimal(metric["valueDecimal"]) or (disclosed.get("start"), disclosed.get("end"), disclosed.get("currency")) != (metric.get("start"), metric.get("end"), metric.get("currency")):
                    result["conflicts"].append(key + "_source_version_difference")
        def relevant_conflicts(identities):
            return [conflict for conflict in observation_conflicts if any(identity and conflict.startswith(identity + "_") for identity in identities)]
        result["conflicts"].extend(relevant_conflicts([row.get("observationId") for row in definition.get("rows", [])] + [definition.get("netIncome"), definition.get("cfo")]))
        if result["conflicts"]:
            result["status"] = "conflict"
        elif result["missing"]:
            result["status"] = "partial"
        groups, group_entries = [], []
        for group in GROUPS:
            entries = [row for row in result["rows"] if row["group"] == group]
            if not entries:
                continue
            with localcontext() as context:
                context.prec = 64
                total = sum((_decimal(row["fact"]["valueDecimal"]) for row in entries), Decimal(0))
            key = "cash_group_" + group
            aggregate = register(_derived(report, period, key, total, [row["fact"] for row in entries],
                                          " + ".join(row["key"] for row in entries), scope=profile["scope"],
                                          cashEffectKind=group, aggregationOnly=True))
            groups.append({"key": key, "labelKey": key, "factId": aggregate["factId"],
                           "rows": [{"key": row["key"], "labelKey": row.get("labelKey", row["key"]), "factId": row["fact"]["factId"]} for row in entries]})
            group_entries.append({"key": key, "fact": aggregate})
        steps = _steps(net_income, cfo, group_entries) if result["status"] == "eligible" else []
        bridge = {key: value for key, value in result.items() if key != "rows"}
        bridge.update(steps=steps, groupedSteps=steps,
                      detailSteps=_steps(net_income, cfo, result["rows"]) if result["status"] == "eligible" else [], groups=groups)
        scope_definition = profile.get("cashScope", {})
        scope_result = {"parts": [], "shares": {}, "checks": [], "missing": []}
        for phase, date_value in (("begin", period["beginningDate"]), ("end", period["end"])):
            phase_definition = scope_definition.get(phase, {})
            values = {key: get(phase_definition.get(key)) for key in ("cash", "restricted", "total")}
            phase_result = evaluate_cash_scope(**values, date=date_value, currency=profile["currency"], scope=profile["scope"])
            phase_result["conflicts"].extend(relevant_conflicts(phase_definition.values()))
            if phase_result["conflicts"]:
                phase_result["status"] = "conflict"
            for key, fact in values.items():
                period["analysis"]["facts"]["cash_scope_" + phase + "_" + key] = fact["factId"] if fact else None
            scope_result[phase] = phase_result
            scope_result["checks"].append(phase_result["check"])
            scope_result["missing"].extend(phase + "_" + key for key in phase_result["missing"])
            shares = {}
            for key in ("cash", "restricted"):
                fact = values[key]
                total = values["total"]
                with localcontext() as context:
                    context.prec = 64
                    proportion = _decimal(fact["valueDecimal"]) / _decimal(total["valueDecimal"]) * 100 if fact and total and _decimal(total["valueDecimal"]) > 0 and phase_result["status"] == "eligible" else None
                share = register(_derived(report, period, "cash_scope_" + phase + "_" + key + "_share", proportion,
                                           [fact, total], key + " / cashflow_cash * 100", unit="percent", scope=profile["scope"],
                                           start=None, end=date_value, measurementDate=date_value))
                shares[key + "FactId"] = share["factId"] if share else None
            scope_result["shares"][phase] = shares
        scope_result["parts"] = [{"key": key, "labelKey": "cash_scope_" + key,
                                  "beginFactId": scope_result["begin"][key + "FactId"], "endFactId": scope_result["end"][key + "FactId"]} for key in ("cash", "restricted", "total")]
        scope_result["status"] = "conflict" if any(scope_result[phase]["status"] == "conflict" for phase in ("begin", "end")) else "eligible" if all(scope_result[phase]["status"] == "eligible" for phase in ("begin", "end")) else "partial"
        if not scope_definition:
            scope_result = {"status": "unavailable", "parts": [], "shares": {}, "checks": [], "missing": [],
                            **{phase: {"status": "unavailable", "missing": [], "conflicts": [],
                                       "cashFactId": None, "restrictedFactId": None, "totalFactId": None}
                               for phase in ("begin", "end")}}
        merchant = {"rows": [], "missing": [], "status": "partial"}
        settlement = profile.get("settlements", {})
        flow_definitions = {row["key"]: row for row in settlement.get("flows", [])}
        balance_definitions = {row["key"]: row for row in settlement.get("balances", [])}
        for key in dict.fromkeys([*balance_definitions, *flow_definitions]):
            entry = balance_definitions.get(key, {})
            begin, end = get(entry.get("begin")), get(entry.get("end"))
            cash_effect = get(flow_definitions.get(key, {}).get("observationId"))
            for prefix, fact in (("begin_", begin), ("end_", end)):
                period["analysis"]["facts"][prefix + key] = fact["factId"] if fact else None
            period["analysis"]["facts"]["cf_" + key] = cash_effect["factId"] if cash_effect else None
            valid = all(_compatible(fact, start=None, end=point, currency=profile["currency"], scope=profile["scope"]) for fact, point in ((begin, period["beginningDate"]), (end, period["end"])) if fact)
            if cash_effect and (not _compatible(cash_effect, start=period["start"], end=period["end"], currency=profile["currency"], scope=profile["scope"]) or cash_effect.get("disclosureKind") != "cash_flow_adjustment"):
                valid = False
            if relevant_conflicts([entry.get("begin"), entry.get("end"), flow_definitions.get(key, {}).get("observationId")]):
                valid = False
            if not valid:
                merchant["status"] = "conflict"
            with localcontext() as context:
                context.prec = 64
                movement = _decimal(end["valueDecimal"]) - _decimal(begin["valueDecimal"]) if valid and begin and end else None
            change = register(_derived(report, period, key + "_balance_change", movement,
                                       [end, begin], "end_" + key + " - begin_" + key,
                                       scope=profile["scope"], interpretation="Balance movement only; not the cashflow adjustment and not available funds."))
            merchant["rows"].append({"key": key, "labelKey": entry.get("labelKey", key), "beginFactId": begin["factId"] if begin else None,
                                     "endFactId": end["factId"] if end else None, "changeFactId": change["factId"] if change else None,
                                     "cashEffectFactId": cash_effect["factId"] if cash_effect else None})
            if not begin or not end:
                merchant["missing"].append(key + "_balance_anchors")
            if not cash_effect:
                merchant["missing"].append(key + "_cashflow_effect")
        if merchant["status"] != "conflict" and merchant["rows"] and not merchant["missing"]:
            merchant["status"] = "eligible"
        if not settlement:
            merchant["status"] = "unavailable"
        overall_status = "conflict" if "conflict" in {result["status"], scope_result["status"], merchant["status"]} else result["status"]
        research = {"type": "cash_research", "profileId": profile["id"], "status": overall_status,
                    "bridge": bridge, "cashScope": scope_result, "merchant": merchant,
                    "noteKeys": profile.get("noteKeys", []), "methodVersion": METHOD_VERSION}
        section = next(row for row in period["analysis"]["sections"] if row["id"] == "cash_conversion")
        section["cashResearch"] = research
        section["status"] = result["status"]
        section["checks"] = [result["check"], *scope_result["checks"]]
        section["rows"] = [{"key": "net_income", "labelKey": "net_income", "factId": net_income["factId"] if net_income else None},
                           *[{"key": row["key"], "labelKey": row.get("labelKey", row["key"]), "factId": row["fact"]["factId"]} for row in result["rows"]],
                           {"key": "cfo", "labelKey": "cfo", "factId": cfo["factId"] if cfo else None}]
        section["missing"] = list(dict.fromkeys([*result["missing"], *result["conflicts"]]))
        old_check = period["reconciliation"].get("check")
        items = [dict(net_income, nameKey="net_income", kind="profit")] if net_income else []
        items += [dict(row["fact"], nameKey=row["key"], kind="noncash" if row["group"] == "noncash" else "working_capital") for row in result["rows"]]
        period["reconciliation"] = {"status": result["status"], "items": items, "steps": steps,
                                    "detailSteps": bridge["detailSteps"], "missing": section["missing"], "check": result["check"],
                                    "sourceReview": review, "profileId": profile["id"]}
        period["views"]["reconciliation"] = result["status"]
        period["checks"] = [check for check in period.get("checks", []) if check != old_check] + [result["check"]]
        if result["status"] == "eligible":
            period["insights"] = [row for row in period.get("insights", []) if row.get("key") != "operating_adjustments_incomplete"]
    return report
