"""Finite fixture response selection. No SAP source approval or inference.

These scripts describe only the existing fictional worksheets and collect user
reports. A fixture admitted here is usable ONLY by this deterministic demo
renderer; it is never admitted into the production SAP generation context.
"""

import re

from consultant.diagnosis_manager import DiagnosisManager, TurnResult
from consultant.intent_classifier import ISSUE_DIAGNOSIS, IntentClassifier
from consultant.message_parser import is_unknown
from offline_demo.fixtures import records
from offline_demo.tcode_references import (
    basics_answer,
    is_basics_question,
    lookup_codes,
    reference_answer,
)
from rag.evidence import citation_handle, record_digest

UNSUPPORTED = "This offline demo has no supporting fixture for that question. Try invoice status, goods receipt, inspection, or PO release."

# Frozen original TEST_ONLY envelopes, not a registry of approved SAP sources.
CATALOG = {r["id"]: (record_digest(r), r) for r in records()}
TREE_TOPICS = {
    "invoice_posting": "invoice",
    "goods_receipt": "receipt",
    "po_release": "release",
    "authorization": "authorization",
    "sales_order": "sales",
}
SOURCE_TITLES = {
    "invoice": "Invoice status",
    "receipt": "Goods receipt",
    "inspection": "Quality inspection",
    "release": "PO release",
    "authorization": "Authorization checks",
    "sales": "Sales order",
}
FIELD_LABELS = {
    "transaction": "transaction",
    "error_message": "on-screen message",
    "po_number": "purchase order",
    "material": "material",
    "company_code": "company code",
    "account": "account",
    "release_group": "release group",
    "release_code": "release code",
    "user_id": "user ID",
    "su53_object": "authorization object",
    "sales_area": "sales area",
    "order_number": "sales order",
}
QUESTIONS = {
    "transaction": "Which screen or transaction were you using? It's fine to say 'not sure' if you don't know the code.",
    "error_message": "Do you remember any message on screen? A few words are enough, or say 'no error message' if none appeared.",
    "po_number": "Do you have the purchase order reference for this example? If not, we can leave it unknown.",
    "material": "Which material was involved, if you have that detail?",
    "company_code": "Do you know the company code for this fictional example? We can leave it unknown if not.",
    "account": "Is an account reported in the example? If you don't have it, just say 'unknown'.",
    "release_group": "Do you know the release group? It's okay if that detail isn't available.",
    "release_code": "Is a release code available, or should we leave it unknown?",
    "user_id": "Which fictional user ID is involved, if you have it?",
    "su53_object": "Is an authorization object reported in the available trace? If there's no trace, say so.",
    "sales_area": "Do you have the sales area for this example? It's fine if it's unknown.",
    "order_number": "Do you have the sales order reference, or is it unavailable?",
}
SCRIPTS = {
    "invoice": "In this example, the fictional invoice is reported posted but payment-blocked; the cause is unknown. First distinguish a posting failure from a payment block.",
    "receipt": "The goods-receipt example has no error number. Collect the transaction or activity, purchase order, material and exact message if available. Missing details leave the cause unconfirmed.",
    "inspection": "The fictional inspection lot has no reported results or decision. Ask whether either is available; missing information does not establish a quality judgment.",
    "release": "The fictional PO has an unknown release group and code. Collect the transaction and exact message, keeping unavailable fields unknown. No approval limit or release outcome is supplied.",
    "authorization": "The fictional user has no available trace or authorization object. Ask for available details and keep absent evidence unknown. No role grant is simulated.",
    "sales": "The fictional sales order has an unknown sales area. Collect the reported transaction and symptom; no document lookup or cause is established.",
}


def prohibited(query):
    return bool(
        re.search(
            r"\bFFC\b|Fauji Fertilizer|\b(?:ignore|override|bypass)\b.*\b(?:instructions|rules|safeguards)\b|"
            r"\b(?:reveal|secrets|password|salary|price|tax|tolerance|configuration|customizing|approval limit)\b",
            query,
            re.I,
        )
    )


def topic_for(query):
    text = query.lower()
    command = re.fullmatch(
        r"demo fixture: (invoice|inspection|receipt|release|authorization|sales)", text
    )
    if command:
        return command[1]
    if re.search(r"\bpayment[- ]block(?:ed)?\b", text):
        return "invoice"
    if re.search(r"\binvoice\b", text) and re.search(
        r"not processing|fail|problem|not posted|posting|not working", text
    ):
        return "invoice"
    if "goods receipt" in text and re.search(
        r"fail|problem|cannot|unable|not working", text
    ):
        return "receipt"
    if re.search(r"\binspection (?:lot|results)\b|\busage decision\b", text):
        return "inspection"
    if re.search(r"\b(?:po|purchase order)\b", text) and re.search(r"releas", text):
        return "release"
    if re.search(r"not authorized|no authorization|access denied", text):
        return "authorization"
    if "sales order" in text and re.search(r"not visible|cannot|fail", text):
        return "sales"
    return None


def unavailable_detail(query):
    # Narrow exception for the existing scenario's missing tolerance report;
    # never use a generic "I don't know" prefix to bypass company/injection bans.
    return bool(
        re.fullmatch(
            r"I (?:don't|do not) know (?:the )?(?:configured )?tolerance[.!]*",
            query,
            re.I,
        )
    )


class DemoClassifier(IntentClassifier):
    def classify(self, query):
        # Explicit repair questions otherwise masked by the informational guard.
        if re.search(r"\binvoice\b.*\bnot processing\b", query, re.I) or (
            re.search(r"goods receipt", query, re.I)
            and re.search(r"what should i do if|what should i check", query, re.I)
            and re.search(r"fails?|failed", query, re.I)
        ):
            return {
                "intent": ISSUE_DIAGNOSIS,
                "source": "offline_demo_rules",
                "confidence": 1.0,
            }
        return super().classify(query)


class DemoDiagnosisManager(DiagnosisManager):
    def __post_init__(self):
        super().__post_init__()
        self.turns = {}

    def delete_session(self, session_id):
        self.turns.pop(session_id, None)
        return super().delete_session(session_id)

    def handle_turn(self, session_id, user_message, history=None):
        if prohibited(user_message) and not unavailable_detail(user_message):
            turn = TurnResult(
                mode="direct", intent="General SAP Query", include_history=False
            )
            self.turns[session_id] = turn
            return turn
        state = self.session_store.get(session_id)
        codes = lookup_codes(
            user_message, collecting=bool(state and state.status == "collecting")
        )
        if codes or is_basics_question(user_message):
            state = self.session_store.get_or_create(session_id)
            # Explicit lookup is a side question, not a reported transaction or
            # answer to a pending field. Explicit topic switches still clear state.
            if state and re.search(
                r"^new question\s*:|^now\s|\binstead[.!?]*$", user_message, re.I
            ):
                state.reset()
            turn = TurnResult(
                mode="direct",
                intent="General SAP Query",
                include_history=False,
                standalone_query=user_message,
            )
            self.turns[session_id] = turn
            return turn
        # A repair question should start/switch the incident rather than act as
        # an informational interruption. Preserve the actual question in memory.
        if "goods receipt" in user_message.lower() and re.search(
            r"what should i do if.*fails?", user_message, re.I
        ):
            user_message = "My goods receipt fails. " + user_message
        turn = super().handle_turn(session_id, user_message, history)
        state = self.session_store.get(session_id)
        if (
            turn.mode == "clarify"
            and state
            and not state.conflicts
            and len(state.unknown_fields) >= 2
            and state.tree_id in TREE_TOPICS
        ):
            # Stop the questionnaire after two unavailable details. Unasked
            # fields remain "not provided", not invented or confirmed absent.
            turn = self._ready_to_diagnose(
                state, self.tree_loader.get_tree(state.tree_id)
            )
        self.turns[session_id] = turn
        return turn


def select_response(engine, query, payload, filters=None):
    if payload.get("error"):
        return payload
    state = engine.diagnosis_store.get(engine.memory.session_id)
    turn = engine.diagnosis_manager.turns.get(engine.memory.session_id)
    codes = lookup_codes(query) if turn and turn.mode == "direct" else None
    basics = turn and turn.mode == "direct" and is_basics_question(query)
    if (codes or basics) and not prohibited(query):
        result = dict(payload)
        result.update(
            basics_answer(filters) if basics else reference_answer(codes, filters)
        )
        if engine.memory.messages and engine.memory.messages[-1]["role"] == "assistant":
            engine.memory.messages[-1]["content"] = result["answer"]
        return result
    explicit = bool(re.fullmatch(r"DEMO fixture: \w+", query, re.I))
    topic = topic_for(query)
    if not topic and turn and turn.mode in ("diagnose", "clarify") and state:
        topic = TREE_TOPICS.get(state.tree_id)
    # Unknown technical details in an active diagnosis must remain usable as
    # unknowns, even when naming an unsupported diagnostic field (e.g. tolerance).
    unavailable_reply = state and unavailable_detail(query)
    if prohibited(query) and not unavailable_reply:
        topic = None
        blocked = True
    else:
        blocked = False
    result = dict(payload)
    if not topic:
        # Generic ambiguous-incident clarification remains the actual engine's
        # question, rather than being converted into an unsupported answer.
        if turn and turn.mode == "clarify" and not blocked:
            return payload
        result.update(answer=UNSUPPORTED, sources=[])
    else:
        candidate = next(
            (
                r
                for r in engine.retriever.search(
                    f"DEMO fixture: {topic}", filters=filters, top_k=6
                )
                if r["id"] == f"TEST_ONLY-{topic}"
            ),
            None,
        )
        original = CATALOG[f"TEST_ONLY-{topic}"]
        if not candidate or record_digest(candidate) != original[0]:
            result.update(answer=UNSUPPORTED, sources=[])
        else:
            handle = citation_handle(candidate)
            if turn and turn.mode == "clarify" and not explicit:
                # Real form question, with unverified example codes omitted.
                question = re.sub(r"\s*\(e\.g\.[^)]*\)", "", payload["answer"])
                question = question.replace(
                    "I need some additional information before diagnosing the issue.\n\n",
                    "",
                )
                if not state.conflicts:
                    question = QUESTIONS.get(state.pending_field, question)
                acknowledgement = (
                    "That's okay—we can leave that detail unknown. "
                    if is_unknown(query)
                    else ""
                )
                answer = acknowledgement + question
            elif explicit:
                answer = f"{candidate['content']} [{handle}]"
            else:
                reported = ""
                if state and turn and turn.mode == "diagnose" and state.answers:
                    reported = (
                        "User-reported: "
                        + "; ".join(
                            f"{FIELD_LABELS.get(key, key.replace('_', ' '))}: {value}"
                            for key, value in state.answers.items()
                        )
                        + ". "
                    )
                if (
                    state
                    and state.symptom_corrected
                    and turn
                    and turn.mode == "diagnose"
                ):
                    reported += f"Corrected user report: {state.opening_message}. "
                if (
                    turn
                    and turn.mode == "diagnose"
                    and payload.get("phase") == "preliminary"
                ):
                    known = (
                        reported
                        or f"So far, you've reported a problem with {SOURCE_TITLES[topic].lower()}, but no technical details are available. "
                    )
                    missing = ", ".join(
                        FIELD_LABELS.get(key, key.replace("_", " "))
                        for key in turn.unknown_fields
                    )
                    priority = next(
                        (
                            key
                            for key in (
                                "error_message",
                                "transaction",
                                "po_number",
                                "material",
                                "su53_object",
                                "sales_area",
                                "release_group",
                                "company_code",
                            )
                            if key in turn.unknown_fields
                        ),
                        None,
                    )
                    next_step = (
                        f"When available, share the {FIELD_LABELS[priority]}"
                        if priority
                        else "Share any additional detail when available"
                    )
                    answer = (
                        f"We can pause the questions here. {known}\n\n"
                        f"Still unavailable or not provided: {missing}. These details are not confirmed evidence. "
                        f"{next_step}, and we can continue from there. I can't identify a cause from the information so far. [{handle}]"
                    )
                else:
                    answer = f"{reported}{SCRIPTS[topic]} [{handle}]"
            result.update(
                answer=answer,
                sources=[
                    {
                        "id": candidate["id"],
                        "citation_handle": handle,
                        "title": SOURCE_TITLES[topic],
                        "source_file": "offline_demo/fixtures.py",
                        "source_kind": "synthetic",
                        "authority": "TEST_ONLY fixture; not SAP documentation",
                        "applicability": candidate["metadata"]["applicability"],
                        "metadata": {},
                        "content_preview": "",
                        "score": candidate["score"],
                    }
                ],
            )
    if engine.memory.messages and engine.memory.messages[-1]["role"] == "assistant":
        engine.memory.messages[-1]["content"] = result["answer"]
    return result
