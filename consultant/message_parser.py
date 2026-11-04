"""Conservative extraction of user-supplied details, not SAP fact validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_UNKNOWN = re.compile(
    r"^(?:(?:i(?:\s+am|'m)?|we(?:\s+are|'re)?)\s+)?(?:do\s+not\s+know|don'?t\s+know|not\s+sure|unsure|unknown|"
    r"unavailable|not\s+available|n/?a|none|skip|no\s+(?:exact\s+)?error(?:\s+message)?|"
    r"there\s+is\s+no\s+error(?:\s+message)?|can'?t\s+(?:find|provide|check)\s+it)"
    r"(?:\s+(?:(?:about\s+)?(?:the\s+)?(?:transaction|release\s+(?:group|code)|error\s+message)|appears|shown))?[.!?]*$",
    re.I,
)
CORRECTION = re.compile(
    r"\b(actually|correction|correcting|instead|rather than|i meant)\b", re.I
)
_TRANSACTION = re.compile(
    r"\b(?:[A-Z]{1,4}\d{2,3}[A-Z0-9]{0,2}|MIGO|MIRO|SPRO|PFCG)\b", re.I
)
_TABLES = {"T001", "T001W", "USR02"}


def _outside_quotes(text: str) -> str:
    return re.sub(
        r"""(?<!\w)(?:"[^"\n]*"|'[^'\n]*'|“[^”\n]*”)""",
        lambda match: (
            match.group()[0] + "\x00" * (len(match.group()) - 2) + match.group()[-1]
        ),
        text,
    )


def is_unknown(text: str) -> bool:
    cleaned = text.strip().replace("’", "'")
    return bool(
        _UNKNOWN.fullmatch(cleaned)
        or (
            not re.search(r"[;\n]|\b(?:but|however)\b", cleaned, re.I)
            and re.match(
                r"^(?:maybe|probably|i think|i guess|not sure\b)", cleaned, re.I
            )
        )
        or (
            not re.search(r"[;\n]|\b(?:but|however)\b", cleaned, re.I)
            and re.fullmatch(
                r"(?:(?:i|we)\s+(?:do not|don't)\s+know\b.+|"
                r"(?:there is\s+)?no\s+(?:real\s+)?(?:SAP\s+)?"
                r"(?:error(?:\s+(?:message|number|code))?|authorization\s+trace|SU53\s+(?:output|result|object))"
                r"(?:\s+(?:is\s+)?(?:available|supplied|provided))?)[.!?]*",
                cleaned,
                re.I,
            )
        )
        or re.fullmatch(
            r"(?:the\s+)?(?:company\s+code|(?:authorization|auth)\s+object|authorization\s+trace|SU53\s+(?:output|result))"
            r"\s+(?:(?:is|was)\s+)?(?:not\s+(?:known|available|provided|supplied)|unavailable|missing)[.!?]*|"
            r"no\s+(?:company\s+code|(?:authorization|auth)\s+object)\s+(?:(?:is|was)\s+)?(?:available|provided|supplied)[.!?]*",
            cleaned,
            re.I,
        )
    )


def transaction_codes(text: str, outside_quotes: bool = False) -> list[str]:
    values = []
    scanned = _outside_quotes(text) if outside_quotes else text
    for match in _TRANSACTION.finditer(scanned):
        value = match.group().upper()
        # Exclude negated alternatives and table-shaped identifiers already used by the classifier.
        if value in _TABLES or re.search(
            r"\b(?:not|rather than)\s*$", text[: match.start()], re.I
        ):
            continue
        if value not in values:
            values.append(value)
    return values


_LABELS = {
    "transaction": r"transaction(?:\s+code)?|t-?code",
    "error_message": r"(?:exact\s+)?error(?:\s+message)?|message",
    "release_group": r"release[ _]+group",
    "release_code": r"release[ _]+code",
    "po_number": r"(?:purchase\s+order|po)(?:\s+(?:number|no\.?))?",
    "material": r"material(?:\s+(?:number|id))?",
    "sales_area": r"sales[ _]+area",
    "order_number": r"(?:sales\s+)?order\s+(?:number|no\.?)",
    "shipping_point": r"shipping[ _]+point",
    "company_code": r"company[ _]+code",
    "account": r"g/l\s+account|gl\s+account|vendor",
    "user_id": r"(?:sap\s+)?user[ _]+id",
    "su53_object": r"(?:su53\s+)?(?:authorization|auth)\s+object",
    "module": r"(?:sap\s+)?module",
    "steps_taken": r"steps\s+(?:taken|tried)",
}
_SIMPLE_FIELDS = set(_LABELS) - {"error_message", "sales_area", "steps_taken"}


def unknown_applies_to(text: str, field_name: str, *, allow_bare: bool = True) -> bool:
    """Bare uncertainty answers the pending question; named absence stays scoped.

    An unavailable trace means its authorization object is unavailable, not known.
    Unmodeled subjects (for example tolerance) must not fill a company-code slot.
    """
    if not is_unknown(text):
        return False
    labels = dict(_LABELS)
    labels["error_message"] += r"|(?:real\s+)?SAP\s+error\s+(?:number|code)"
    labels["su53_object"] += r"|authorization\s+trace|SU53\s+(?:output|result)"
    named = {
        name
        for name, label in labels.items()
        if re.search(rf"\b(?:{label})\b", text, re.I)
    }
    if named:
        return field_name in named
    if not allow_bare:
        return False
    cleaned = text.strip().replace("’", "'")
    # Only a subject-free uncertainty can stand for the currently requested field.
    return bool(_UNKNOWN.fullmatch(cleaned)) or bool(
        re.fullmatch(
            r"(?:maybe|probably|i think|i guess)(?:\s+[\w/-]+)?[.!?]*", cleaned, re.I
        )
    )


def valid_field_reply(field_name: str, value: str) -> bool:
    """Validate identifier shape only, never SAP existence or field-length rules."""
    if is_unknown(value):
        return False
    if field_name in {
        "company_code",
        "account",
        "user_id",
        "su53_object",
        "release_group",
        "release_code",
    }:
        return bool(
            re.fullmatch(r"[\w/.-]+(?:\s+\(fictional\))?", value.strip(), re.I)
        ) and value.casefold() not in {
            "missing",
            "unavailable",
            "unknown",
            "none",
            "not",
            "no",
            "yes",
        }
    return True


@dataclass
class ExtractedDetails:
    values: dict[str, str] = field(default_factory=dict)
    unknown: dict[str, str] = field(default_factory=dict)
    conflicts: dict[str, list[str]] = field(default_factory=dict)


def extract_details(text: str, allowed_fields: tuple[str, ...]) -> ExtractedDetails:
    """Read labeled fields and explicit code-shaped tokens without inferring company values."""
    result = ExtractedDetails()
    if is_unknown(text):
        for name in allowed_fields:
            if unknown_applies_to(text, name, allow_bare=False):
                result.unknown[name] = "not provided by user"
        return result
    matches = []
    label_text = _outside_quotes(text)
    for name, label in _LABELS.items():
        target = (
            "sales_order"
            if name == "order_number" and "sales_order" in allowed_fields
            else name
        )
        if target not in allowed_fields:
            continue
        if re.search(
            rf"\b(?:don'?t know|do not know|not sure(?: about)?)\s+(?:the\s+)?(?:{label})\b",
            text.replace("’", "'"),
            re.I,
        ):
            result.unknown[target] = "not provided by user"
        # Free-text errors require a delimiter or quotes; 'error in MIGO' is not exact error text.
        delimiter = (
            r"\s*(?::|=|\bis\b|\bsays\b)\s*|\s+(?=[\"'“])"
            if name == "error_message"
            else r"\s*(?::|=|\bis\b)\s*|\s+"
        )
        pattern = rf"\b(?:{label})(?:{delimiter})"
        matches.extend(
            (m.start(), m.end(), target) for m in re.finditer(pattern, label_text, re.I)
        )
    matches.sort()
    candidates: dict[str, list[str]] = {}
    for i, (_, end, name) in enumerate(matches):
        limit = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        raw = text[end:limit].strip()
        quoted = re.match(r"""["'“](.*?)["'”](?:\s|[;,!.]|$)""", raw)
        value = quoted.group(1) if quoted else re.split(r"[;,\n]", raw, maxsplit=1)[0]
        value = re.sub(r"\s+(?:and|with|for)$", "", value.strip(), flags=re.I).strip(
            " ."
        )
        if not value:
            continue
        if is_unknown(value):
            result.unknown[name] = value
            continue
        # Validate the full reply before taking a token. Otherwise prose such as
        # 'a fictional placeholder' could become a supposedly supplied code 'a'.
        if not valid_field_reply(name, value):
            continue
        if name in _SIMPLE_FIELDS:
            value = value.split()[0].strip(".,!\"'")
            if value.lower() in {
                "not",
                "is",
                "failed",
                "cannot",
                "unknown",
                "no",
                "the",
            }:
                continue
        if not valid_field_reply(name, value):
            continue
        candidates.setdefault(name, []).append(value)

    if (
        "transaction" in allowed_fields
        and "transaction" not in candidates
        and "transaction" not in result.unknown
    ):
        codes = transaction_codes(text, outside_quotes=True)
        for quoted in re.finditer(
            r"""\b(?:using|in|running)\s+["'“]([A-Z0-9_/]+)["'”]""", text, re.I
        ):
            codes.extend(
                code for code in transaction_codes(quoted.group(1)) if code not in codes
            )
        if re.fullmatch(r"""["'“][A-Z0-9_/]+["'”]""", text.strip(), re.I):
            codes = transaction_codes(text)
        if codes:
            candidates["transaction"] = codes
    # These are explicitly DEMO document labels, not claims about executable SAP IDs.
    for target, pattern in {
        "po_number": r"\bDEMO_PO_[A-Z0-9_]+\b",
        "order_number": r"\bDEMO_SO_[A-Z0-9_]+\b",
    }.items():
        if (
            target in allowed_fields
            and target not in candidates
            and target not in result.unknown
        ):
            values = re.findall(pattern, label_text, re.I)
            if values:
                candidates[target] = values
    if "error_message" in allowed_fields and "error_message" not in candidates:
        if re.search(r"\bno\s+(?:exact\s+)?error\s+message\b", text, re.I):
            result.unknown["error_message"] = "no error message"
        else:
            error_id = re.search(r"\berror\s+([A-Z]{1,3}\d?\s+\d{3})\b", text, re.I)
            if error_id:
                candidates["error_message"] = [error_id.group(1)]
            else:
                quoted_error = re.search(
                    r"""\b(?:says|shows|getting|receiving)\s+["'“](.*?)["'”]""",
                    text,
                    re.I,
                )
                if quoted_error:
                    candidates["error_message"] = [quoted_error.group(1)]
    if (
        "module" in allowed_fields
        and "module" not in candidates
        and "module" not in result.unknown
    ):
        module = re.search(r"\b(?:SAP|in)\s+(MM|SD|FI|CO|PP|PM|QM)\b", label_text, re.I)
        if module:
            candidates["module"] = [module.group(1).upper()]

    for name, values in candidates.items():
        unique = list(
            dict.fromkeys(v.upper() if name == "transaction" else v for v in values)
        )
        if len(unique) > 1 and not CORRECTION.search(text):
            result.conflicts[name] = unique
        else:
            result.values[name] = unique[-1]
        result.unknown.pop(name, None)
    return result
