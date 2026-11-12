"""Validate AI-selected official observations before they enter fixed calculations."""
from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import urlsplit

from .core import _check, _decimal, _digest, _fact, _percent, _text, _value
from .filing_xbrl import parse_filing
from .providers import ReportError
from .sec_cache import read_json, sha


def require(condition, message):
    if not condition:
        raise ReportError("supplement_invalid", message)


def apply_research(workspace, manifest, report, by_year, gaps):
    from .report_v2 import VERSION, DIMENSIONS, local_file
    from .analysis import FLOW_TAGS, BALANCE_TAGS, CF_TAGS
    data = read_json(workspace / "supplements.json")
    require(data.get("version") == VERSION, "Unsupported supplement contract version.")
    for field in ("sources", "facts", "business", "reconciliations", "notes"):
        require(isinstance(data.get(field), list), "Supplement fields must be lists: " + field)
        require(all(isinstance(item, dict) for item in data[field]), "Supplement entries must be objects: " + field)
    currency = report["company"]["currency"]
    cik = report["company"]["cik"]
    sources = {}
    evidence = {}
    source_records = {r["name"]: r for r in manifest["sources"]}
    for record in data["sources"]:
        identity = record.get("id")
        require(isinstance(identity, str) and identity and identity not in sources, "Evidence source IDs must be unique.")
        if record.get("preparedSource"):
            require(record["preparedSource"] in source_records, "Unknown prepared source.")
            source = {**source_records[record["preparedSource"]], **record}
            # Prepared evidence cannot change its URL, hash or acquisition version.
            base = source_records[record["preparedSource"]]
            require(all(source.get(k) == base[k] for k in ("file", "url", "sha256", "retrievedAt")), "Prepared evidence provenance cannot be overridden.")
        else:
            source = record
        path = local_file(workspace, source.get("file", ""))
        body = path.read_bytes()
        require(source.get("sha256") == sha(body), "Official evidence document hash mismatch.")
        require(source.get("cik") == cik and source.get("currency") == currency, "Evidence source issuer or currency mismatch.")
        url = urlsplit(source.get("url", ""))
        require(url.scheme == "https" and url.hostname and not url.username and not url.password, "Evidence requires a credential-free official HTTPS URL.")
        official_sec = url.hostname in {"www.sec.gov", "sec.gov", "www.sec.gov"} and re.match(r"/Archives/edgar/data/0*" + str(int(cik)) + r"/", url.path)
        official_ir = url.hostname in {urlsplit(u if "://" in u else "https://" + u).hostname for u in manifest["identity"]["officialWebsites"]}
        # An IR domain can be established by a preserved link from this issuer's SEC filing.
        if not official_ir and source.get("officialLinkSource") in source_records:
            link_source = source_records[source["officialLinkSource"]]
            if link_source["name"].startswith("filing-"):
                link_body = local_file(workspace, link_source["file"]).read_text(encoding="utf-8", errors="replace")
                official_ir = bool(re.search(r'href=["\']https?://' + re.escape(url.hostname) + r'(?:/|["\'])', link_body, re.I))
        require(official_sec or official_ir, "IR evidence needs an official issuer website or a link in a preserved SEC filing.")
        require(isinstance(source.get("publishedAt"), str) and source["publishedAt"] <= manifest["asOf"], "Evidence publication date exceeds the prepared cutoff.")
        require(isinstance(source.get("retrievedAt"), str) and bool(source["retrievedAt"]), "Evidence acquisition timestamp is required.")
        candidates, text = parse_filing(body)
        if source.get("textFile"):
            text_body = local_file(workspace, source["textFile"]).read_bytes()
            require(sha(text_body) == source.get("textSha256"), "PDF/extracted evidence text hash mismatch.")
            text = text_body.decode("utf-8")
        sources[identity] = source
        evidence[identity] = {"candidates": {row["id"]: row for row in candidates}, "text": text}
    observations = {}
    placements = set()
    metric_placements = set()
    resolved = []
    periods = {p["year"]: p for p in report["periods"]}
    for item in data["facts"]:
        identity = item.get("id")
        require(isinstance(identity, str) and identity and identity not in observations, "Observation IDs must be unique.")
        year, key = item.get("year"), item.get("key")
        require(type(year) is int and year in periods and isinstance(key, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key), "Unknown observation year or metric key.")
        p = periods[year]
        allowed = set(p["metrics"]) | set(FLOW_TAGS) | {"raw_" + k for k in CF_TAGS}
        allowed |= {prefix + k for k in BALANCE_TAGS for prefix in ("begin_", "end_")}
        require(key in allowed or key == "business_revenue" or key.startswith("cf_"), "Unknown supplement metric; use a prepared key or an explicit cf_ adjustment.")
        require(item.get("sourceId") in sources, "Observation source is missing.")
        source = sources[item["sourceId"]]
        require(item.get("currency") == currency and item.get("scope") == "consolidated" and item.get("unit") == "currency", "Observation currency, scope or unit mismatch.")
        expected_start = None if key in {"assets", "liabilities", "equity", "bs_cash", "ppe", "rou", "cash_begin", "cash_end"} or key.startswith(("begin_", "end_")) else p["start"]
        expected_end = p["beginningDate"] if key == "cash_begin" or key.startswith("begin_") else p["end"]
        require((item.get("start"), item.get("end")) == (expected_start, expected_end), "Observation actual period differs from its target.")
        require(isinstance(item.get("location"), str) and item["location"].strip() and isinstance(item.get("mappingNote"), str) and item["mappingNote"].strip(), "Evidence row/column location and mapping rationale are required.")
        require(all(isinstance(item.get(k), str) and re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", item[k]) for k in ("documentValue", "multiplier")), "Original amounts and multipliers must be finite decimal strings.")
        amount = _decimal(item.get("documentValue"))
        multiplier = _decimal(item.get("multiplier"))
        require(amount is not None and multiplier in {Decimal(10) ** power for power in range(13)}, "Use an original decimal amount and a documented power-of-ten multiplier.")
        value = amount * multiplier
        if "valueDecimal" in item:
            require(_decimal(item["valueDecimal"]) == value, "Supplement normalized amount differs from document amount times multiplier.")
        ev = evidence[item["sourceId"]]
        if item.get("documentFactId"):
            candidate = ev["candidates"].get(item["documentFactId"])
            require(candidate and candidate.get("valueDecimal") is not None, "Inline XBRL candidate is missing or has an unsupported number format.")
            require(_decimal(candidate["valueDecimal"]) == value and (candidate.get("start"), candidate.get("end")) == (expected_start, expected_end), "Inline XBRL value or context differs from the observation.")
            require(str(candidate.get("cik")).zfill(10) == cik and candidate["measures"] == ["iso4217:" + currency], "Inline XBRL entity or unit differs.")
            require(candidate["dimensions"] == item.get("dimensions", {}), "Inline XBRL dimensions differ from the selected observation.")
            placement = (source["sha256"], candidate["tag"], candidate["start"], candidate["end"],
                         _digest(candidate["dimensions"]), tuple(candidate["measures"]))
        else:
            raw = item.get("rawText")
            require(isinstance(raw, str) and raw.strip() and raw in ev["text"], "Preserve the exact original amount token in readable source text.")
            if raw.strip() in {"—", "–", "-"}:
                require(amount == 0 and item.get("zeroInterpretation"), "A disclosed dash needs explicit nil interpretation.")
            else:
                token = re.sub(r"[\s,$]", "", raw.strip()).replace("\u2212", "-")
                if token.startswith("(") and token.endswith(")"):
                    token = "-" + token[1:-1]
                require(_decimal(token) == amount, "Original source token differs from the supplied document decimal.")
            placement = (source["sha256"], item["location"], expected_start, expected_end)
        require(placement not in placements, "Duplicate underlying source row/context; reference the existing observation instead.")
        placements.add(placement)
        require(item.get("role", "leaf") in {"leaf", "total", "subtotal"}, "Unknown source row role.")
        dimensions = item.get("dimensions", {})
        require(isinstance(dimensions, dict), "Observation dimensions must be an object.")
        if key != "business_revenue":
            require(not dimensions, "Consolidated core metrics cannot contain segment dimensions.")
            require((year, key) not in metric_placements, "Duplicate observation for a fiscal year and metric.")
            metric_placements.add((year, key))
        fact = _fact(key, {"valueDecimal": _text(value), "factId": "observation-" + _digest([source["sha256"], item])[:24],
                          "start": expected_start, "end": expected_end, "source_url": source["url"], "tag": item.get("tag"),
                          "filed": source["publishedAt"], "status": "manually_selected"}, currency, source["retrievedAt"], "IR_manual",
                     unit="currency", originalMultiplier=item["multiplier"], scope="consolidated", location=item["location"],
                     sourceFile=source["file"], sourceHash=source["sha256"], documentFactId=item.get("documentFactId"),
                     mappingNote=item["mappingNote"], sourceId=item["sourceId"], rowRole=item.get("role", "leaf"), dimensions=dimensions,
                     name=item.get("name", key), nameKey=item.get("labelKey", key))
        fact["sourceIdentity"] = list(placement)
        observations[identity] = fact
        if key == "business_revenue":
            continue
        existing = by_year[year].get(key)
        conflict = next((g for g in gaps if g["year"] == year and g["key"] == key and g["status"] == "ambiguous_latest_values"), None)
        resolution = item.get("resolution", {})
        if existing and existing["valueDecimal"] != fact["valueDecimal"]:
            require(resolution.get("supersedes") == [existing["factId"]] and resolution.get("reason") and source["publishedAt"] >= existing["filed"], "Conflicting SEC evidence needs an explicit version resolution.")
        if conflict:
            require(resolution.get("versions") == conflict["versions"] and resolution.get("reason"), "Ambiguous structured facts need an explicit resolution of all candidate versions.")
        if resolution:
            resolved.append({"year": year, "key": key, "resolution": resolution, "observation": identity})
        if existing and existing["valueDecimal"] == fact["valueDecimal"]:
            fact["equivalentFactId"] = existing["factId"]
        by_year[year][key] = fact
        if key in p["metrics"]:
            p["metrics"][key] = fact
    business_years = set()
    for group in data["business"]:
        year = group.get("year")
        require(year in periods and year not in business_years, "Duplicate or unknown business year.")
        business_years.add(year)
        require(group.get("dimension") in DIMENSIONS and isinstance(group.get("definition"), str) and group["definition"].strip(), "Business classification and definition are required.")
        require(type(group.get("comparableToPrevious")) is bool, "Business comparability must be explicit.")
        require(group["comparableToPrevious"] or group.get("comparabilityNote"), "Noncomparable business periods need an explanation.")
        ids = group.get("facts", [])
        require(isinstance(ids, list) and ids and len(set(ids)) == len(ids) and all(i in observations for i in ids), "Business rows must reference distinct observations.")
        items = [observations[i] for i in ids]
        require(all(f["key"] == "business_revenue" and f["start"] == periods[year]["start"] and f["end"] == periods[year]["end"] and f["rowRole"] == "leaf" and _value(f) >= 0 for f in items), "Business rows must be nonnegative period-matched leaves; totals cannot be added with children.")
        require(len({f["name"] for f in items}) == len(items), "Business member names must be distinct.")
        revenue = periods[year]["metrics"]["revenue"]
        total = sum((_value(f) for f in items), Decimal(0))
        check = _check("business_sum_equals_revenue", total, _value(revenue), [f["factId"] for f in items] + ([revenue["factId"]] if revenue else []))
        for index, fact in enumerate(items):
            share = _value(fact) / _value(revenue) * 100 if revenue and _value(revenue) > 0 else None
            fact.update(id=fact["factId"], dimension=group["dimension"], shareDecimal=_text(share), shareDisplay=_percent(share),
                        presentation={"color": ["blue", "orange", "green", "gray", "purple"][index % 5]})
        periods[year]["business"] = {"status": "eligible" if check["status"] == "match" and group.get("complete") is True else "conflict" if check["status"] == "mismatch" else "partial",
                                      "items": items, "dimension": group["dimension"], "definition": group["definition"], "checks": [check],
                                      "missing": [] if check["status"] == "match" and group.get("complete") is True else ["complete_business_mapping"],
                                      "comparableToPrevious": group["comparableToPrevious"], "comparabilityNote": group.get("comparabilityNote")}
    reconciliation_years = set()
    for group in data["reconciliations"]:
        year = group.get("year")
        require(year in periods and year not in reconciliation_years, "Duplicate or unknown reconciliation year.")
        reconciliation_years.add(year)
        ids = group.get("facts", [])
        require(isinstance(ids, list) and ids and len(set(ids)) == len(ids) and all(i in observations for i in ids), "Reconciliation rows must reference distinct observations.")
        review = group.get("review", {})
        require(review.get("complete") is True and review.get("rows") == ids and review.get("location") and review.get("sourceId") in sources, "A complete reconciliation needs an explicit original-table row-set review.")
        p = periods[year]
        items = [observations[i] for i in ids]
        require(items[0]["key"] == "net_income" and items[0]["valueDecimal"] == (p["metrics"]["net_income"] or {}).get("valueDecimal"), "Reconciliation must start with the matching net income.")
        require(all(f["start"] == p["start"] and f["end"] == p["end"] and f["sourceId"] == review["sourceId"] for f in items), "CFO rows must belong to one reviewed original table and period.")
        require(all(f["rowRole"] == "leaf" and f["key"].startswith("cf_") for f in items[1:]), "CFO adjustment rows must be distinct leaves; subtotals cannot be added.")
        for fact in items:
            fact["kind"] = "profit" if fact["key"] == "net_income" else "disclosed_adjustment"
        check = _check("reviewed_rows_equal_cfo", sum((_value(f) for f in items), Decimal(0)), _value(p["metrics"]["cfo"]), [f["factId"] for f in items])
        p["reconciliation"] = {"status": "eligible" if check["status"] == "match" else "conflict", "items": items,
                               "check": check, "missing": [] if check["status"] == "match" else ["source_row_set_does_not_reconcile"], "review": review}
    formation_policies = {}
    require(isinstance(data.get("incomeFormations", []), list), "Income formation reviews must be a list.")
    for group in data.get("incomeFormations", []):
        require(isinstance(group, dict), "Income formation entries must be objects.")
        year = group.get("year")
        require(year in periods and year not in formation_policies, "Duplicate or unknown income formation year.")
        ids = group.get("facts", [])
        require(isinstance(ids, list) and ids and len(set(ids)) == len(ids) and all(i in observations for i in ids), "Income formation must cite distinct original observations.")
        review = group.get("review", {})
        require(review.get("complete") is True and review.get("rows") == ids and review.get("location") and review.get("sourceId") in sources, "Income formation needs a complete nonoperating table review.")
        items = [observations[i] for i in ids]
        p = periods[year]
        allowed = {"nonoperating_income", "interest_income", "interest_expense", "other_nonoperating_income", "nonoperating_fx_gain_loss", "investment_gain", "equity_method_income"}
        require(all(f["key"] in allowed and f["start"] == p["start"] and f["end"] == p["end"] and f["sourceId"] == review["sourceId"] for f in items), "Income formation rows must match the reviewed source, period and allowed concepts.")
        keys = [f["key"] for f in items]
        require(len(set(keys)) == len(keys) and ("nonoperating_income" not in keys or len(keys) == 1), "Nonoperating totals and components cannot be added together.")
        require(all(f["rowRole"] == "leaf" for f in items) or keys == ["nonoperating_income"], "Income formation components cannot contain subtotals.")
        formation_policies[year] = {"mode": "aggregate" if keys == ["nonoperating_income"] else "components",
                                    "nonoperatingKeys": ["interest_expense_effect" if key == "interest_expense" else key for key in keys],
                                    "pretaxKey": "pretax_income", "afterTaxKeys": [], "observationKey": "v2IncomeFormation"}
    notes = []
    for note in data["notes"]:
        require(isinstance(note, dict) and note.get("sourceId") in sources and note.get("text") and note.get("location"), "Research notes need an official source and location.")
        notes.append({**note, "url": sources[note["sourceId"]]["url"]})
    return {"notes": notes, "sources": list(sources.values()), "sourceCount": len(sources), "observationCount": len(observations), "resolutions": resolved, "formationPolicies": formation_policies,
            "evidenceHash": sha((workspace / "supplements.json").read_bytes())}
