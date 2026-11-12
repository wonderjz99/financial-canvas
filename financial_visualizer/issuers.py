"""Validated issuer identities and declarative, non-executable report profiles."""

from __future__ import annotations

import copy
from datetime import date
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "issuers.json"
SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,19}$")


class RegistryError(ValueError):
    """An issuer profile failed the local configuration contract."""


def _require(condition, message):
    if not condition:
        raise RegistryError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _strings(value):
    return isinstance(value, list) and all(_text(item) for item in value) and len(set(value)) == len(value)


def _object(value, required, label):
    _require(isinstance(value, dict) and set(required) <= set(value), "Invalid " + label)


def _period(value):
    try:
        start, end = date.fromisoformat(value["start"]), date.fromisoformat(value["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RegistryError("Invalid configured actual period") from exc
    _require(start <= end, "Configured period starts after its end")


def _source_file(value):
    _require(_text(value) and not PurePosixPath(value).is_absolute()
             and ".." not in PurePosixPath(value).parts and "\\" not in value,
             "Configured source files must be project-relative paths")


def _source_url(value):
    try:
        parsed = urlparse(value) if isinstance(value, str) else None
    except ValueError as exc:
        raise RegistryError("Configured disclosure URL is malformed") from exc
    _require(parsed and parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password,
             "Configured disclosure URLs must use credential-free HTTPS")


def _analysis(value):
    _object(value, ("formation", "notes", "turnover", "assetPurchaseKey", "supplements", "cfFromIncome", "cfDirect"), "analysis profile")
    formation = value["formation"]
    _object(formation, ("mode", "nonoperatingKeys", "pretaxKey", "afterTaxKeys", "observationKey"), "income formation profile")
    _require(_text(formation["mode"]) and formation["mode"] in {"aggregate", "components", "unavailable"}, "Unknown income formation mode")
    for key in ("nonoperatingKeys", "afterTaxKeys"):
        _require(_strings(formation[key]), "Invalid income formation members")
    members = formation["nonoperatingKeys"] + formation["afterTaxKeys"]
    _require(len(set(members)) == len(members), "Repeated income formation member")
    _require("nonoperating_income" not in formation["nonoperatingKeys"] or len(formation["nonoperatingKeys"]) == 1,
             "A nonoperating total must not be added with its components")
    if formation["mode"] == "unavailable":
        _require(not members, "Unavailable income formation cannot declare financial members")
    else:
        _require(formation["nonoperatingKeys"] and _text(formation["pretaxKey"])
                 and _text(formation["observationKey"]), "Income formation requires explicit concepts")
    if formation["mode"] == "aggregate":
        _require(len(formation["nonoperatingKeys"]) == 1, "Aggregate formation requires a single nonoperating total")
    _require(formation["pretaxKey"] is None or _text(formation["pretaxKey"]), "Invalid pretax concept")
    _require(formation["observationKey"] is None or _text(formation["observationKey"]), "Invalid formation explanation")
    _object(value["notes"], ("profitScope", "cashConversion", "workingCapital", "workingMissing", "quality"), "analysis notes")
    _require(all(item is None or _text(item) for item in value["notes"].values()), "Invalid analytical explanation key")
    _require(_text(value["assetPurchaseKey"]) or value["assetPurchaseKey"] is None, "Invalid asset-purchase concept")
    if "cashProfileFile" in value:
        _source_file(value["cashProfileFile"])
    if "additionalFacts" in value:
        _require(_strings(value["additionalFacts"]) and set(value["additionalFacts"]) <= {
            "unearned_revenue", "unearned_revenue_current", "unearned_revenue_noncurrent", "cf_unearned_revenue",
            "finance_lease_assets_obtained", "finance_lease_principal_paid", "finance_lease_interest_paid",
            "common_stock_dividends_paid",
        }, "Invalid additional analysis concepts")
    if "operatingExpenseComponents" in value:
        components = value["operatingExpenseComponents"]
        _require(_strings(components) and components
                 and set(components) <= {"research_development", "selling_general_admin", "sales_marketing", "general_admin"},
                 "Invalid operating expense components")
        _require("selling_general_admin" not in components
                 or not {"sales_marketing", "general_admin"}.intersection(components),
                 "Operating expense total and children must not be added together")
    _require(isinstance(value["turnover"], list), "Invalid turnover profile")
    seen = set()
    for item in value["turnover"]:
        _object(item, ("key", "balanceKey", "denominatorKey", "approximation"), "turnover member")
        _require(all(_text(item[key]) for key in ("key", "balanceKey", "denominatorKey"))
                 and item["key"] not in seen and (item["approximation"] is None or _text(item["approximation"])), "Invalid turnover member")
        seen.add(item["key"])
    for field in ("supplements", "cfFromIncome", "cfDirect"):
        _require(isinstance(value[field], list), "Invalid analytical source selection")
    selections = set()
    for item in value["supplements"]:
        _object(item, ("key", "start", "end", "sourceId"), "supplement selection")
        _period(item)
        _require(_text(item["key"]) and _text(item["sourceId"]), "Invalid supplement reference")
        selection = (item["key"], item["start"], item["end"])
        _require(selection not in selections, "Duplicate disclosure supplement selection")
        selections.add(selection)
    adjustment_keys = set()
    for item in value["cfFromIncome"]:
        _object(item, ("key", "inputKey", "sign", "reviews"), "reviewed cash adjustment")
        _require(_text(item["key"]) and _text(item["inputKey"]) and type(item["sign"]) is int
                 and item["sign"] in {-1, 1} and isinstance(item["reviews"], list), "Invalid cash adjustment sign or reference")
        _require(item["key"] not in adjustment_keys, "Duplicate cash adjustment concept")
        adjustment_keys.add(item["key"])
        periods = set()
        for review in item["reviews"]:
            _object(review, ("start", "end", "sourceUrl", "location", "method"), "cash adjustment review")
            _period(review)
            _source_url(review["sourceUrl"])
            _require(_text(review["location"]) and _text(review["method"]), "Missing cash adjustment placement review")
            point = (review["start"], review["end"])
            _require(point not in periods, "Duplicate cash adjustment review period")
            periods.add(point)
    for item in value["cfDirect"]:
        _object(item, ("key", "rawKey", "tags", "sign", "formula", "contextNote", "kind"), "direct cash adjustment")
        _require(all(_text(item[key]) for key in ("key", "rawKey", "formula", "contextNote"))
                 and _strings(item["tags"]) and item["tags"] and type(item["sign"]) is int
                 and item["sign"] in {-1, 1} and _text(item["kind"])
                 and item["kind"] in {"noncash", "working_capital"}, "Invalid direct cash adjustment")
        _require(isinstance(item.get("reviews"), list), "Direct cash adjustment requires explicit placement reviews")
        _require(item["key"] not in adjustment_keys, "Duplicate cash adjustment concept")
        adjustment_keys.add(item["key"])
        periods = set()
        for review in item["reviews"]:
            _object(review, ("start", "end", "sourceUrl", "location", "method"), "direct cash adjustment review")
            _period(review)
            _source_url(review["sourceUrl"])
            _require(_text(review["location"]) and _text(review["method"]), "Missing direct cash adjustment review")
            point = (review["start"], review["end"])
            _require(point not in periods, "Duplicate direct cash adjustment review period")
            periods.add(point)


def validate_registry(value):
    """Validate only the configuration contract, never imply financial coverage."""
    _object(value, ("schemaVersion", "defaultSymbol", "defaultSymbols", "issuers"), "issuer registry")
    _require(value["schemaVersion"] == "1.0" and isinstance(value["issuers"], dict) and value["issuers"], "Unsupported or empty issuer registry")
    _require(_strings(value["defaultSymbols"]) and value["defaultSymbols"], "Invalid default issuer selection")
    _require(_text(value["defaultSymbol"]) and value["defaultSymbol"] in value["defaultSymbols"]
             and set(value["defaultSymbols"]) <= set(value["issuers"]), "Default issuer is not registered")
    for symbol, profile in value["issuers"].items():
        _require(isinstance(symbol, str) and bool(SYMBOL_PATTERN.fullmatch(symbol)), "Invalid registered symbol")
        _object(profile, ("cik", "currency", "scope", "company", "presentation", "business", "analysis", "reconciliations"), "issuer profile")
        _require(isinstance(profile["cik"], str) and bool(re.fullmatch(r"[0-9]{10}", profile["cik"]))
                 and int(profile["cik"]) > 0, "Invalid SEC issuer identity")
        _require(isinstance(profile["currency"], str) and bool(re.fullmatch(r"[A-Z]{3}", profile["currency"])), "Invalid issuer currency")
        _require(profile["scope"] == "consolidated", "Unsupported issuer entity scope")
        comparisons = profile.get("providerComparisons", {})
        _require(isinstance(comparisons, dict), "Invalid provider comparison configuration")
        for statement, mappings in comparisons.items():
            _require(statement in {"income", "balance", "cashflow"} and isinstance(mappings, dict), "Invalid provider comparison statement")
            for key, mapping in mappings.items():
                _require(_text(key), "Invalid provider comparison concept")
                _object(mapping, ("secKey", "note"), "provider comparison mapping")
                _require(_text(mapping["secKey"]) and _text(mapping["note"]), "Invalid provider comparison reference")
        _object(profile["company"], ("name", "nameZh"), "company display resource")
        _require(all(_text(profile["company"][key]) for key in ("name", "nameZh")), "Missing company display names")
        _object(profile["presentation"], ("cashScopeNoteKey", "businessNoteKey", "sourceSummaryKey"), "presentation profile")
        _require(all(item is None or _text(item) for item in profile["presentation"].values()), "Invalid presentation resource key")
        business = profile["business"]
        if business is not None:
            _object(business, ("dimension", "sourceGroupType", "items"), "business profile")
            _require(_text(business["dimension"]) and business["dimension"] in {"reportable_segment", "service_revenue", "end_market", "geographic_revenue", "revenue_category"}
                     and type(business["sourceGroupType"]) is int and business["sourceGroupType"] >= 0
                     and isinstance(business["items"], dict), "Invalid business dimension or supplier group")
            for name, item in business["items"].items():
                _require(_text(name), "Invalid business item name")
                _object(item, ("color",), "business presentation")
                _require(_text(item["color"]) and item["color"] in {"blue", "orange", "green", "gray", "purple"}
                         and ("labelKey" not in item or _text(item["labelKey"])), "Invalid business presentation")
        _analysis(profile["analysis"])
        _require(isinstance(profile["reconciliations"], list), "Invalid reconciliation source selections")
        periods = set()
        for item in profile["reconciliations"]:
            _object(item, ("start", "end", "sourceFile", "checkId", "noncashKeys"), "reconciliation source")
            _period(item)
            _source_file(item["sourceFile"])
            _require(_text(item["checkId"]) and _strings(item["noncashKeys"]), "Invalid reconciliation source reference")
            point = (item["start"], item["end"])
            _require(point not in periods, "Duplicate reconciliation source period")
            periods.add(point)
    return value


def load_registry(path=None):
    """Read a selected JSON configuration; no code or network is executed."""
    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            _require(key not in result, "Repeated issuer configuration key")
            result[key] = item
        return result
    try:
        value = json.loads((Path(path) if path else REGISTRY_PATH).read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except RegistryError:
        raise
    except (OSError, ValueError) as exc:
        raise RegistryError("The issuer registry could not be read") from exc
    return validate_registry(value)


def _registry(registry):
    return load_registry() if registry is None else validate_registry(registry)


def get_issuer(symbol, registry=None):
    """Return an isolated profile; callers cannot mutate shared configuration."""
    value = _registry(registry)
    if not isinstance(symbol, str) or symbol not in value["issuers"]:
        raise RegistryError("The requested issuer is not registered")
    return copy.deepcopy(value["issuers"][symbol])


def supported_symbols(registry=None):
    return tuple(_registry(registry)["issuers"])


def default_symbols(registry=None):
    return tuple(_registry(registry)["defaultSymbols"])


def default_symbol(registry=None):
    return _registry(registry)["defaultSymbol"]
