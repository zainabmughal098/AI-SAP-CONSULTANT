"""Finite, research-checked demo lookups; never production source admission.

Only code purposes are summarized. No procedures or cross-release equivalence.
Official bodies were read 2026-11-04; see TCODE_REFERENCE_REPORT.md.
"""

import re

from rag.evidence import citation_handle, record_digest

ERP = "https://help.sap.com/http.svc/rc/8c4fa73704904b67991c1b99640945b1/6.05.16/en-US/Chapter_24__Procurement_and_Logistics_ExecutionE.PDF"
S4 = "https://help.sap.com/doc/b870b6ebcd2e4b5890f16f4b06827064/2023.000/en-US/WN_OP2023_EN.pdf"
ADMIN = "https://help.sap.com/doc/b4447b6727684f13917622cf63e1eb98/2023/en-US/AdminGuideS4HANAImpl_HELP_EN.pdf"


def _record(code, description, module, scope, url, title, page):
    return {
        "id": f"DEMO-REFERENCE-{code}",
        "content": description,
        "metadata": {
            "classification": "DEMO reference; purpose lookup only",
            "tcode": code,
            "module": module,
            "applicability": scope,
            "source_url": url,
            "title": title,
            "page": str(page),
            "date_checked": "2026-11-04",
            "limitations": "No execution, repair, configuration or cross-edition applicability established.",
        },
    }


REFERENCES = {}
for code, description in [
    ("ME21N", "ME21N is used to create a purchase order."),
    ("ME22N", "ME22N is used to change an existing purchase order."),
    ("ME23N", "ME23N is used to display a purchase order."),
    ("MIRO", "MIRO is used to enter an invoice in Logistics Invoice Verification."),
]:
    REFERENCES[code] = _record(
        code,
        description,
        "MM",
        "SAP ERP 6.0 EHP5",
        ERP,
        "SAP ERP procurement release notes",
        4 if code == "MIRO" else 14,
    )
for code, description, module, page in [
    ("MIGO", "MIGO is the Goods Movement transaction.", "MM", 1229),
    ("VA01", "VA01 is used to create a sales order.", "SD", 804),
    ("VA02", "VA02 is used to change an existing sales order.", "SD", 804),
    ("VA03", "VA03 is used to display a sales order.", "SD", 804),
]:
    REFERENCES[code] = _record(
        code,
        description,
        module,
        "SAP S/4HANA 2023 (on-premise)",
        S4,
        "SAP S/4HANA 2023 — What's New",
        page,
    )
REFERENCES["SU53"] = _record(
    "SU53",
    "SU53 displays authorization data.",
    "BC",
    "SAP S/4HANA Cloud Private Edition 2023 FP2",
    ADMIN,
    "SAP Private Edition 2023 FP2 administration guide",
    7,
)
REFERENCE_HASHES = {code: record_digest(record) for code, record in REFERENCES.items()}

# Deliberately finite question grammar: arbitrary instructions cannot acquire a
# reference merely by mentioning a known code. Unknown codes never get guessed.
CODE = r"[A-Z][A-Z0-9_/-]{1,39}"


def lookup_codes(query, *, collecting=False):
    text = query.strip().replace("’", "'")
    text = re.sub(r"^(?:new question\s*:\s*|now\s+)", "", text, flags=re.I)
    text = re.sub(r"\s+instead[.!?]*$", "", text, flags=re.I)
    text = text.rstrip(".?!").strip()
    patterns = [
        rf"(?:what is|what's|explain|describe)\s+(?:the\s+)?(?:transaction(?: code)?\s+|t-code\s+)?({CODE})(?:\s+(?:used for|in SAP|used for in SAP))?",
        rf"what(?:'s| is) the difference between\s+({CODE})\s+and\s+({CODE})",
        rf"compare\s+({CODE})\s+(?:and|with|vs\.?)\s+({CODE})",
    ]
    if not collecting:
        patterns.append(rf"({CODE})")
    for pattern in patterns:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            codes = tuple(dict.fromkeys(c.upper() for c in match.groups()))
            # Bare prose is not a transaction lookup, but unknown digit-shaped
            # codes and custom Z/Y codes can be refused explicitly.
            if all(c in REFERENCES or re.search(r"\d", c) for c in codes):
                return codes
    return None


def reference_answer(codes, filters=None):
    if any(code not in REFERENCES for code in codes):
        return {
            "answer": "This offline reference set does not cover every code in that question. I won't guess its purpose.",
            "sources": [],
        }
    records = [REFERENCES[code] for code in codes]
    if any(
        record_digest(r) != REFERENCE_HASHES[c]
        for c, r in zip(codes, records, strict=True)
    ):
        return {
            "answer": "The offline reference failed its integrity check.",
            "sources": [],
        }
    if filters and any(
        key != "module"
        or any(r["metadata"][key].casefold() != str(value).casefold() for r in records)
        for key, value in filters.items()
    ):
        return {
            "answer": "No offline transaction reference matches that filter.",
            "sources": [],
        }
    lines, sources = [], []
    for record in records:
        meta = record["metadata"]
        handle = citation_handle(record)
        lines.append(f"{record['content']} [{handle}]\nScope: {meta['applicability']}.")
        sources.append(
            {
                "id": record["id"],
                "citation_handle": handle,
                "title": f"{meta['tcode']} — SAP reference",
                "source_file": meta["title"],
                "source_url": meta["source_url"],
                "source_kind": "demo_reference",
                "authority": "Official SAP purpose reference; offline demo only; no production approval",
                "applicability": meta["applicability"],
                "metadata": dict(meta),
                "content_preview": "",
            }
        )
    if len({r["metadata"]["applicability"] for r in records}) > 1:
        lines.append(
            "These references cover different releases/editions; this compares their stated purposes only."
        )
    return {"answer": "\n\n".join(lines), "sources": sources}
