"""Illustrative offline display labels, never assignments or outbound actions."""

import re

SUPPORT_AREAS = {
    "po_release": ("release", "Procurement / SAP MM"),
    "invoice_posting": ("invoice", "Finance / SAP FI"),
    "goods_receipt": ("receipt", "Inventory / SAP MM"),
    "sales_order": ("sales", "Sales / SAP SD"),
}


def recommendation(state, turn, topic):
    """Use the current incident only; informational turns never acquire a label."""
    if (
        not state
        or not turn
        or turn.mode not in ("clarify", "diagnose")
        or turn.tree_id != state.tree_id
        or state.conflicts
        or state.tree_id not in SUPPORT_AREAS
    ):
        return ""
    expected_topic, area = SUPPORT_AREAS[state.tree_id]
    if topic != expected_topic:
        return ""

    # A keyword winner is insufficient when the opening reports multiple areas.
    # PO references alone do not make a goods-receipt incident a release issue.
    text = state.opening_message.casefold()
    signals = {
        "release": bool(re.search(r"\b(?:po|purchase order)\b", text))
        and bool(re.search(r"\breleas\w*\b", text)),
        "invoice": bool(re.search(r"\binvoice\b|\bpayment[- ]block\w*\b", text)),
        "receipt": bool(re.search(r"\bgoods receipt\b|\bgr\b", text)),
        "sales": bool(re.search(r"\bsales order\b", text)),
    }
    if {name for name, present in signals.items() if present} != {topic}:
        return ""
    return (
        f"\n\n**Suggested support area:** {area}\n"
        "Status: SIMULATED — No ticket created or forwarded.\n"
        "Illustrative support-area recommendation only. Actual department assignment requires organizational verification."
    )
