"""Read inline XBRL without executing filing HTML or applying custom tag semantics."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from .sec_cache import sha


class FilingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contexts = {}
        self.units = {}
        self.numbers = []
        self.text = []
        self.context = None
        self.unit = None
        self.number = None
        self.capture = None
        self.capture_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        local = tag.split(":")[-1]
        if local == "context":
            self.context = {"id": attrs.get("id"), "dimensions": {}}
        elif local == "unit":
            self.unit = {"id": attrs.get("id")}
        if self.context is not None and local in {"identifier", "startdate", "enddate", "instant", "explicitmember", "typedmember"}:
            self.capture = (local, attrs)
            self.capture_text = []
        elif self.unit is not None and local == "measure":
            self.capture = (local, attrs)
            self.capture_text = []
        if tag == "ix:nonfraction":
            self.number = {"attrs": attrs, "text": [], "excluded": 0}
        elif tag == "ix:exclude" and self.number:
            self.number["excluded"] += 1

    def handle_data(self, data):
        self.text.append(data)
        if self.capture:
            self.capture_text.append(data)
        if self.number is not None and not self.number["excluded"]:
            self.number["text"].append(data)

    def handle_endtag(self, tag):
        local = tag.split(":")[-1]
        if self.capture and local == self.capture[0]:
            key, attrs = self.capture
            value = "".join(self.capture_text).strip()
            if key in {"explicitmember", "typedmember"}:
                self.context["dimensions"][attrs.get("dimension", "unknown")] = value
            elif key == "measure":
                self.unit.setdefault("measures", []).append(value)
            else:
                self.context[key] = value
            self.capture = None
        if local == "context" and self.context is not None:
            self.contexts[self.context["id"]] = self.context
            self.context = None
        elif local == "unit" and self.unit is not None:
            self.units[self.unit["id"]] = self.unit
            self.unit = None
        if tag == "ix:exclude" and self.number:
            self.number["excluded"] -= 1
        if tag == "ix:nonfraction" and self.number is not None:
            self.numbers.append(self.number)
            self.number = None


def parse_filing(body):
    parser = FilingParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    facts = []
    document_hash = sha(body)
    for row in parser.numbers:
        attrs = row["attrs"]
        context = parser.contexts.get(attrs.get("contextref"), {})
        unit = parser.units.get(attrs.get("unitref"), {})
        raw = "".join(row["text"]).strip()
        # Unsupported transformations remain candidates for source review, never guessed.
        fmt = attrs.get("format", "").split(":")[-1].lower()
        value = None
        try:
            if attrs.get("xsi:nil") != "true" and fmt in {"", "num-dot-decimal", "numdotdecimal", "zerodash", "fixed-zero"}:
                normalized = re.sub(r"[\s,$]", "", raw).replace("\u2212", "-")
                if fmt in {"zerodash", "fixed-zero"} and raw in {"—", "–", "-"}:
                    normalized = "0"
                if normalized.startswith("(") and normalized.endswith(")"):
                    normalized = "-" + normalized[1:-1]
                scale = int(attrs.get("scale", "0"))
                if not -12 <= scale <= 12:
                    raise ValueError("Unsupported scale")
                amount = Decimal(normalized) * Decimal(10) ** scale
                if attrs.get("sign") == "-":
                    amount = -amount
                if amount.is_finite() and abs(amount) <= Decimal("1e30"):
                    value = format(amount, "f")
        except (ValueError, InvalidOperation):
            pass
        identity = sha(str([document_hash, attrs, raw]).encode())[:24]
        facts.append({"id": "ix-" + identity, "tag": attrs.get("name"), "contextRef": attrs.get("contextref"),
                      "cik": context.get("identifier"), "start": context.get("startdate"),
                      "end": context.get("enddate") or context.get("instant"),
                      "dimensions": context.get("dimensions", {}), "measures": unit.get("measures", []),
                      "rawValue": raw, "scale": attrs.get("scale", "0"), "sign": attrs.get("sign"),
                      "format": attrs.get("format"), "valueDecimal": value})
    return facts, " ".join(parser.text)
