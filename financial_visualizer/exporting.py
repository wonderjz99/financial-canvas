"""Portable JSON and self-contained HTML exports for the local report."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit
from .issuers import RegistryError, default_symbol, get_issuer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"
DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")


class ExportError(ValueError):
    code = "invalid_report"
    status = 400


def _validate_analysis(analysis, facts):
    """Keep the optional analytical view bound to the validated fact registry."""
    if not isinstance(analysis, dict) or not isinstance(analysis.get("sections"), list) or not isinstance(analysis.get("facts"), dict):
        raise ExportError("Invalid analytical sections or fact lookup")
    allowed = {"profit", "cash_conversion", "working_capital", "cash_uses", "efficiency", "quality"}
    identities = set()

    def reference(identity, optional=False):
        if optional and identity is None:
            return
        if not isinstance(identity, str) or identity not in facts:
            raise ExportError("Analytical reference is missing from the source registry")
        fact = facts[identity]
        if not isinstance(fact, dict) or fact.get("factId") != identity or not isinstance(fact.get("valueDecimal"), str):
            raise ExportError("Analytical fact identity or decimal representation is invalid")
        if fact.get("unit", "currency") not in {"currency", "percent", "days", "times"}:
            raise ExportError("Unsupported analytical fact unit")
        inputs = fact.get("inputs", [])
        if not isinstance(inputs, list) or any(not isinstance(item, str) or item not in facts for item in inputs):
            raise ExportError("Analytical formula input is missing from the source registry")

    for key, identity in analysis["facts"].items():
        if not isinstance(key, str):
            raise ExportError("Invalid analytical fact key")
        reference(identity, optional=True)
    for section in analysis["sections"]:
        if not isinstance(section, dict) or section.get("id") not in allowed or section["id"] in identities:
            raise ExportError("Unknown or duplicate analytical section")
        identities.add(section["id"])
        if not isinstance(section.get("titleKey"), str) or not isinstance(section.get("rows"), list):
            raise ExportError("Invalid analytical section title or rows")
        for row in section["rows"]:
            if not isinstance(row, dict) or not isinstance(row.get("key"), str) or not isinstance(row.get("labelKey"), str):
                raise ExportError("Invalid analytical row")
            reference(row.get("factId"), optional=True)
        for field, kind in (("chart", "profit_bridge"), ("formationChart", "income_formation")):
            chart = section.get(field)
            if chart is None:
                continue
            if not isinstance(chart, dict) or chart.get("type") != kind or not isinstance(chart.get("steps"), list):
                raise ExportError("Invalid analytical chart")
            for step in chart["steps"]:
                if not isinstance(step, dict) or step.get("kind") not in {"total", "flow"}:
                    raise ExportError("Invalid analytical waterfall step")
                reference(step.get("factId"))
                for field in ("startDecimal", "endDecimal"):
                    value = step.get(field)
                    if not isinstance(value, str) or not DECIMAL_PATTERN.fullmatch(value):
                        raise ExportError("Analytical chart coordinates must use financial decimal strings")
        equity_chart = section.get("equityChart")
        if equity_chart is not None:
            if not isinstance(equity_chart, dict) or equity_chart.get("type") != "equity_components" or not isinstance(equity_chart.get("rows"), list):
                raise ExportError("Invalid equity analytical chart")
            reference(equity_chart.get("beginFactId"), optional=True)
            reference(equity_chart.get("endFactId"), optional=True)
            for row in equity_chart["rows"]:
                if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ("key", "labelKey", "relation")):
                    raise ExportError("Invalid equity analytical row")
                reference(row.get("factId"), optional=True)
        research = section.get("cashResearch")
        if research is not None:
            if section["id"] != "cash_conversion" or not isinstance(research, dict) or research.get("type") != "cash_research":
                raise ExportError("Invalid cash research view")
            if research.get("status") not in {"eligible", "partial", "conflict"} or not isinstance(research.get("profileId"), str):
                raise ExportError("Invalid cash research status or profile identity")
            bridge = research.get("bridge")
            if not isinstance(bridge, dict) or bridge.get("status") not in {"eligible", "partial", "conflict"}:
                raise ExportError("Invalid reviewed cash bridge")
            for field in ("steps", "groupedSteps", "detailSteps"):
                steps = bridge.get(field)
                if not isinstance(steps, list) or (steps and bridge["status"] != "eligible"):
                    raise ExportError("Incomplete cash research cannot expose a closed bridge")
                for step in steps:
                    if not isinstance(step, dict) or step.get("kind") not in {"total", "flow"}:
                        raise ExportError("Invalid reviewed cash bridge step")
                    reference(step.get("factId"))
                    if any(not isinstance(step.get(key), str) or not DECIMAL_PATTERN.fullmatch(step[key]) for key in ("startDecimal", "endDecimal")):
                        raise ExportError("Cash research geometry must use decimal strings")
            groups = bridge.get("groups")
            if not isinstance(groups, list):
                raise ExportError("Invalid cash adjustment groups")
            for group in groups:
                if not isinstance(group, dict) or not all(isinstance(group.get(key), str) for key in ("key", "labelKey")) or not isinstance(group.get("rows"), list):
                    raise ExportError("Invalid cash adjustment group")
                reference(group.get("factId"))
                for row in group["rows"]:
                    if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ("key", "labelKey")):
                        raise ExportError("Invalid grouped cash adjustment")
                    reference(row.get("factId"))
            cash_scope = research.get("cashScope")
            if not isinstance(cash_scope, dict) or not isinstance(cash_scope.get("parts"), list) or not isinstance(cash_scope.get("shares"), dict):
                raise ExportError("Invalid cash definition analysis")
            for phase in ("begin", "end"):
                point = cash_scope.get(phase)
                if not isinstance(point, dict):
                    raise ExportError("Invalid cash definition endpoint")
                for key in ("cashFactId", "restrictedFactId", "totalFactId"):
                    reference(point.get(key), optional=True)
                for identity in cash_scope["shares"].get(phase, {}).values():
                    reference(identity, optional=True)
                    if identity and facts[identity].get("unit") != "percent":
                        raise ExportError("Cash definition shares require percentage facts")
            for row in cash_scope["parts"]:
                if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ("key", "labelKey")):
                    raise ExportError("Invalid cash definition component")
                reference(row.get("beginFactId"), optional=True)
                reference(row.get("endFactId"), optional=True)
            merchant = research.get("merchant")
            if not isinstance(merchant, dict) or not isinstance(merchant.get("rows"), list):
                raise ExportError("Invalid settlement analysis")
            for row in merchant["rows"]:
                if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ("key", "labelKey")):
                    raise ExportError("Invalid settlement row")
                for key in ("beginFactId", "endFactId", "changeFactId", "cashEffectFactId"):
                    reference(row.get(key), optional=True)
            if not isinstance(research.get("noteKeys"), list) or any(not isinstance(key, str) for key in research["noteKeys"]):
                raise ExportError("Invalid cash research explanation keys")
        if not isinstance(section.get("observations", []), list) or not isinstance(section.get("missing", []), list):
            raise ExportError("Invalid analytical observations or missing fields")
        if any(not isinstance(key, str) for key in section.get("missing", [])):
            raise ExportError("Invalid missing analytical field")
        for observation in section.get("observations", []):
            if not isinstance(observation, dict) or not isinstance(observation.get("messageKey"), str) or not isinstance(observation.get("params", {}), dict):
                raise ExportError("Invalid analytical observation")
            if not isinstance(observation.get("refs", []), list):
                raise ExportError("Invalid analytical observation references")
            for identity in observation.get("refs", []):
                reference(identity)
            if any(not isinstance(value, (str, int, bool, type(None))) for value in observation.get("params", {}).values()):
                raise ExportError("Analytical display parameters must be scalar text or integers")


def validate_report_payload(report, registry=None):
    """Validate the portable boundary, not the truth of imported financial facts."""
    if not isinstance(report, dict) or report.get("schemaVersion") != "1.0":
        raise ExportError("Unsupported report schema")
    try:
        configuration = get_issuer(report.get("symbol"), registry)
    except RegistryError as exc:
        raise ExportError("Unsupported report symbol or issuer configuration") from exc
    years = report.get("years")
    periods = report.get("periods")
    if (not isinstance(years, list) or not 1 <= len(years) <= 20
            or any(type(year) is not int for year in years)
            or sorted(set(years)) != years or not isinstance(periods, list)
            or len(periods) != len(years)):
        raise ExportError("Invalid report periods")
    if [period.get("year") for period in periods if isinstance(period, dict)] != years:
        raise ExportError("Period list does not match fiscal years")
    if not isinstance(report.get("facts"), dict) or not isinstance(report.get("company"), dict):
        raise ExportError("Missing company or facts")
    if report["company"].get("currency") != configuration["currency"]:
        raise ExportError("Report currency must match the issuer's native reporting currency")
    if report["company"].get("cik") != configuration["cik"]:
        raise ExportError("Report identity must match the issuer registry")
    if not isinstance(report.get("snapshot"), dict) or not isinstance(report["snapshot"].get("id"), str) or not report["snapshot"]["id"]:
        raise ExportError("Missing report snapshot identity")
    for period in periods:
        for field in ("metrics", "profit", "cash", "balance", "business", "reconciliation", "ratios", "views"):
            if not isinstance(period.get(field), dict):
                raise ExportError(f"Invalid period section: {field}")
        for field in ("business", "reconciliation"):
            if not isinstance(period[field].get("items"), list):
                raise ExportError(f"Invalid period items: {field}")
        for fact in period["metrics"].values():
            if fact is not None:
                if not isinstance(fact, dict) or fact.get("factId") not in report["facts"]:
                    raise ExportError("Metric fact is missing from the source registry")
                registered = report["facts"][fact["factId"]]
                if fact.get("valueDecimal") != registered.get("valueDecimal") or fact.get("currency") != report["company"]["currency"]:
                    raise ExportError("Metric fact differs from its source registry or currency")
        if "analysis" in period:
            _validate_analysis(period["analysis"], report["facts"])

    def walk(value, depth=0):
        if depth > 32:
            raise ExportError("Report nesting exceeds limit")
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("Decimal") and item is not None:
                    if not isinstance(item, str) or len(item) > 120 or not DECIMAL_PATTERN.fullmatch(item):
                        raise ExportError("Financial decimals must be finite decimal strings")
                if key in {"sourceUrl", "source_url", "source_document_url"} and item:
                    if not isinstance(item, str) or urlsplit(item).scheme not in {"https", "http"}:
                        raise ExportError("Source URLs must use HTTP or HTTPS")
                walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ExportError("Report numbers must be finite")
    walk(report)
    return report


def report_json(report, registry=None):
    validate_report_payload(report, registry)
    return json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


def script_json(value):
    """Keep external text inside its JSON script context."""
    return (json.dumps(value, ensure_ascii=False, allow_nan=False)
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _asset(relative):
    path = (WEB_ROOT / urlsplit(relative).path.lstrip("/")).resolve()
    if not path.is_relative_to(WEB_ROOT.resolve()) or not path.is_file():
        raise ExportError("Missing local export asset")
    return path.read_text()


def render_html(report, registry=None, *, single_company=False):
    """Bundle one or both companies into one offline, dependency-free HTML."""
    if isinstance(report, dict) and "schemaVersion" in report:
        reports = {report["symbol"]: report}
    elif isinstance(report, dict) and report:
        reports = report
    else:
        raise ExportError("Expected a report or a company report registry")
    for symbol, value in reports.items():
        validate_report_payload(value, registry)
        if symbol != value["symbol"]:
            raise ExportError("Company registry key differs from report symbol")
    default_report = reports.get(default_symbol(registry)) or next(iter(reports.values()))
    page = (WEB_ROOT / "index.html").read_text()
    locale = json.loads((WEB_ROOT / "zh-CN.json").read_text())
    if single_company:
        locale.update(json.loads((WEB_ROOT / "single-company.zh-CN.json").read_text(encoding="utf-8")))
        for fact in default_report["facts"].values():
            if fact.get("name"):
                for key in (fact.get("key"), fact.get("nameKey"), "ir_" + fact.get("nameKey", fact.get("key", ""))):
                    if key:
                        locale.setdefault(key, fact["name"])
    styles = []
    scripts = []

    def inline_style(match):
        styles.append(_asset(match.group(1)))
        return ""

    def collect_script(match):
        scripts.append(_asset(match.group(1)))
        return ""

    page = re.sub(r'<link\b[^>]*href=["\']([^"\']+\.css(?:\?[^"\']*)?)["\'][^>]*>', inline_style, page, flags=re.I)
    page = re.sub(r'<script\b[^>]*src=["\']([^"\']+)["\'][^>]*>\s*</script\s*>', collect_script, page, flags=re.I)
    if single_company:
        styles.append(_asset("single-company.css"))
        scripts.append(_asset("single-company.js"))
    if not scripts:
        raise ExportError("No application scripts found for export")
    page_title = '财务动态图 · ' + ' / '.join(reports)
    page = re.sub(r'<title>.*?</title>', '<title>' + page_title + '</title>', page, flags=re.I | re.S)
    page = page.replace("</head>", "<style>\n" + "\n".join(styles) + "\n</style>\n</head>")
    bootstrap = "<script>window.__FV_REPORTS__=" + script_json(reports) + ";window.__FV_REPORT__=window.__FV_REPORTS__[" + script_json(default_report["symbol"]) + "];window.__FV_LOCALE__=" + script_json(locale) + ";window.__FV_OFFLINE__=true;</script>"
    script_tags = "\n".join("<script>\n" + re.sub(r'</script', r'<\\/script', source, flags=re.I) + "\n</script>" for source in scripts)
    return page.replace("</body>", bootstrap + "\n" + script_tags + "\n</body>")


def render_single_html(report, registry):
    """V2 export: exactly one company, using its verified ephemeral identity profile."""
    if not isinstance(report, dict) or report.get("delivery", {}).get("mode") != "single_company":
        raise ExportError("V2 export requires a prepared single-company report")
    return render_html(report, registry=registry, single_company=True)
