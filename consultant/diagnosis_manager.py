"""Orchestrate intent classification, clarification, and enriched diagnosis queries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from consultant.clarification_engine import ClarificationEngine
from consultant.diagnosis_tree_loader import (
    DiagnosisTree,
    DiagnosisTreeLoader,
    get_default_loader,
)
from consultant.intent_classifier import (
    ISSUE_DIAGNOSIS,
    IntentClassifier,
    is_information_request,
    reports_problem,
)
from consultant.message_parser import (
    CORRECTION,
    extract_details,
    is_unknown,
    transaction_codes,
    unknown_applies_to,
)
from consultant.session_state import DiagnosisSessionStore, DiagnosisState
from rag.config.settings import AppSettings

TurnMode = Literal["clarify", "diagnose", "direct"]


@dataclass
class TurnResult:
    mode: TurnMode
    intent: str
    message: str | None = None
    enriched_query: str | None = None
    answers: dict[str, str] = field(default_factory=dict)
    tree_id: str | None = None
    phase: str = "answering"
    unknown_fields: dict[str, str] = field(default_factory=dict)
    preliminary: bool = False
    include_history: bool = True
    standalone_query: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "intent": self.intent,
            "message": self.message,
            "enriched_query": self.enriched_query,
            "answers": dict(self.answers),
            "tree_id": self.tree_id,
            "phase": self.phase,
            "unknown_fields": dict(self.unknown_fields),
            "preliminary": self.preliminary,
        }


@dataclass
class DiagnosisManager:
    """Single entry point used by SAPConsultant before retrieval."""

    settings: AppSettings | None = None
    session_store: DiagnosisSessionStore = field(default_factory=DiagnosisSessionStore)
    tree_loader: DiagnosisTreeLoader | None = None
    intent_classifier: IntentClassifier | None = None
    clarification: ClarificationEngine = field(default_factory=ClarificationEngine)

    def __post_init__(self) -> None:
        if self.tree_loader is None:
            self.tree_loader = get_default_loader()
        if self.intent_classifier is None:
            self.intent_classifier = IntentClassifier(settings=self.settings)

    def handle_turn(
        self,
        session_id: str,
        user_message: str,
        history: list[dict[str, str]] | None = None,
    ) -> TurnResult:
        # Durable-per-process diagnosis state is canonical, not the browser transcript.
        state = self.session_store.get_or_create(session_id)
        text = user_message.strip()
        if re.fullmatch(
            r"(?:cancel(?: this diagnosis)?|reset|start over|forget this issue)[.!]*",
            text,
            re.I,
        ):
            state.reset()
            return TurnResult(
                mode="clarify",
                intent="General SAP Query",
                phase="answering",
                message="Diagnosis cleared. Please ask a new SAP question.",
            )

        routed = re.sub(
            r"^(?:new (?:issue|question|topic)\s*[:,-]?\s*|now\s+)",
            "",
            text,
            flags=re.I,
        )
        routed = re.sub(r"\s+instead[.!]*$", "", routed, flags=re.I)
        switched = bool(
            re.search(
                r"\b(?:new (?:issue|question|topic)|different (?:problem|topic)|switch to|forget (?:that|the previous))\b",
                text,
                re.I,
            )
        )
        switched = switched or (
            is_information_request(routed)
            and bool(re.search(r"\binstead\b|^now\b", text, re.I))
        )
        if switched:
            state.reset()

        if state.tree_id:
            tree = self.tree_loader.get_tree(state.tree_id)
            if tree:
                if re.fullmatch(
                    r"(?:resume(?: (?:the )?diagnosis)?|continue diagnosis)[.!]*",
                    text,
                    re.I,
                ):
                    return self._advance(state, tree)
                # Apply explicitly supplied details before handling 'still fails' or
                # guidance requests, so a correction cannot be hidden in a follow-up.
                information_request = is_information_request(routed)
                candidate = self.tree_loader.match_tree(routed)
                if (
                    not information_request
                    and reports_problem(routed)
                    and candidate.id not in (tree.id, "generic_issue")
                    and re.match(r"^(?:my|our|i|we)\b", routed, re.I)
                    and not CORRECTION.search(routed)
                ):
                    return self._start_or_resume_diagnosis(
                        state, routed, ISSUE_DIAGNOSIS
                    )
                details = extract_details(text, tree.required_fields)
                if (
                    is_unknown(text)
                    and state.status != "collecting"
                    and not (details.values or details.unknown or details.conflicts)
                ):
                    # An unmodeled unavailable detail is still part of this
                    # incident, not a standalone question or a supplied value.
                    return self._ready_to_diagnose(state, tree)
                if (
                    not information_request
                    and CORRECTION.search(text)
                    and reports_problem(text)
                    and not (details.values or details.unknown or details.conflicts)
                ):
                    # A symptom correction is a new user report, not a field reply
                    # or proof of a root cause. Retain identifiers, retire stale symptoms.
                    state.opening_message = text
                    state.symptom_corrected = True
                    state.followups.clear()
                    if "error_message" in state.answers:
                        state.mark_unknown(
                            "error_message",
                            "previous symptom superseded; current exact message unavailable",
                        )
                    return self._ready_to_diagnose(state, tree)
                if not information_request and (
                    details.values
                    or details.unknown
                    or details.conflicts
                    or CORRECTION.search(text)
                ):
                    if re.search(
                        r"\b(?:preliminary guidance|skip the rest|still|same issue)\b",
                        text,
                        re.I,
                    ):
                        self._merge_details(state, details, text)
                        return (
                            self._advance(state, tree)
                            if state.conflicts
                            else self._ready_to_diagnose(state, tree)
                        )
                    if state.status == "collecting":
                        return self._continue_collection(state, text)
                    self._merge_details(state, details, text)
                    return (
                        self._advance(state, tree)
                        if state.conflicts
                        else self._ready_to_diagnose(state, tree)
                    )
                if re.search(
                    r"\b(?:preliminary guidance|skip the rest|help with what|use what (?:you|we) have)\b",
                    text,
                    re.I,
                ):
                    return self._ready_to_diagnose(state, tree)
                if re.search(
                    r"\b(?:what (?:should|can) i (?:check|try|do)(?: next)?|what next)\b",
                    text,
                    re.I,
                ):
                    return self._ready_to_diagnose(state, tree)
                if re.search(
                    r"\b(?:still|same issue)\b|\b(?:it|that|this)\b.*\b(?:not working|fails?|blocked|not releasing)\b",
                    text,
                    re.I,
                ):
                    state.followups = (state.followups + [text])[-5:]
                    return self._ready_to_diagnose(state, tree)
                # Explanations are side questions unless the user explicitly switched topics.
                if is_information_request(routed):
                    query = routed
                    if re.search(r"\b(?:that|this|it|mentioned)\b", routed, re.I):
                        reported = "; ".join(
                            f"{name}: {value}" for name, value in state.answers.items()
                        )
                        query = f"Current user-reported details (unverified): {reported}\nQuestion: {routed}"
                    return TurnResult(
                        mode="direct",
                        intent=self.intent_classifier.classify(routed)["intent"],
                        include_history=False,
                        standalone_query=query,
                    )
                if state.status == "collecting":
                    return self._continue_collection(state, text)
                if reports_problem(text) or re.search(
                    r"\b(?:still|same issue|tried that|what next|that did not help)\b",
                    text,
                    re.I,
                ):
                    state.followups = (state.followups + [text])[-5:]
                    return self._ready_to_diagnose(state, tree)

        classification = self.intent_classifier.classify(routed)
        if classification["intent"] == ISSUE_DIAGNOSIS:
            return self._start_or_resume_diagnosis(state, routed, ISSUE_DIAGNOSIS)
        return TurnResult(
            mode="direct",
            intent=classification["intent"],
            include_history=not switched,
            standalone_query=routed if switched else None,
        )

    def _start_or_resume_diagnosis(
        self, state: DiagnosisState, user_message: str, intent: str
    ) -> TurnResult:
        tree = self.tree_loader.match_tree(user_message)
        state.reset()
        state.intent = tree.intent
        state.tree_id = tree.id
        state.opening_message = user_message
        state.status = "collecting"
        self._merge_details(
            state, extract_details(user_message, tree.required_fields), user_message
        )
        return self._advance(state, tree)

    def _merge_details(self, state: DiagnosisState, details, text: str) -> None:
        corrected = bool(CORRECTION.search(text))
        for name, reason in details.unknown.items():
            state.mark_unknown(name, reason)
        for name, values in details.conflicts.items():
            previous = state.answers.get(name)
            state.mark_conflict(name, ([previous] if previous else []) + values)
        for name, value in details.values.items():
            previous = state.answers.get(name)
            if previous and previous.casefold() != value.casefold() and not corrected:
                state.mark_conflict(name, [previous, value])
            elif (
                name in state.conflicts
                and value not in state.conflicts[name]
                and not corrected
            ):
                state.mark_conflict(name, state.conflicts[name] + [value])
            else:
                state.record_answer(name, value)

    def _continue_collection(
        self, state: DiagnosisState, user_message: str
    ) -> TurnResult:
        tree = self.tree_loader.get_tree(state.tree_id or "")
        if tree is None:
            state.reset()
            return TurnResult(
                mode="direct",
                intent="General SAP Query",
                phase="answering",
                include_history=False,
            )
        pending = state.pending_field
        details = extract_details(user_message, tree.required_fields)
        has_details = bool(details.values or details.unknown or details.conflicts)
        self._merge_details(state, details, user_message)
        if state.conflicts and pending not in state.conflicts:
            return self._advance(state, tree)
        if pending and not has_details:
            if is_unknown(user_message):
                if unknown_applies_to(user_message, pending):
                    state.mark_unknown(pending, user_message)
            elif pending in state.conflicts:
                if user_message.strip() in state.conflicts[pending]:
                    state.record_answer(pending, user_message.strip())
            elif not CORRECTION.search(user_message):
                duplicate = user_message.strip().casefold() in {
                    v.casefold() for v in state.answers.values()
                }
                if not duplicate and (
                    pending != "transaction" or transaction_codes(user_message)
                ):
                    self.clarification.apply_user_answer(state, user_message)
        if (
            pending
            and state.pending_field == pending
            and pending not in state.conflicts
        ):
            state.invalid_replies[pending] = state.invalid_replies.get(pending, 0) + 1
            if state.invalid_replies[pending] < 2:
                label = pending.replace("_", " ")
                return TurnResult(
                    mode="clarify",
                    intent=ISSUE_DIAGNOSIS,
                    phase="clarifying",
                    tree_id=tree.id,
                    answers=dict(state.answers),
                    message=f"Your other details are retained. Please provide {label}, say 'I don't know', or request preliminary guidance.",
                )
            state.mark_unknown(pending, "not provided after clarification")
        return self._advance(state, tree)

    def _advance(self, state: DiagnosisState, tree: DiagnosisTree) -> TurnResult:
        if state.conflicts:
            name = next(iter(state.conflicts))
            state.invalid_replies[name] = state.invalid_replies.get(name, 0) + 1
            if state.invalid_replies[name] > 1:
                state.mark_unknown(name, "conflicting values not resolved")
                return self._advance(state, tree)
            state.mark_asked(name)
            choices = " / ".join(state.conflicts[name])
            return TurnResult(
                mode="clarify",
                intent=ISSUE_DIAGNOSIS,
                phase="clarifying",
                answers=dict(state.answers),
                tree_id=tree.id,
                message=f"You supplied conflicting values for {name.replace('_', ' ')}: {choices}. Which should I use? You can say 'I don't know'.",
            )
        question = self.clarification.ask_next(tree, state)
        if question is None:
            return self._ready_to_diagnose(state, tree)
        return TurnResult(
            mode="clarify",
            intent=ISSUE_DIAGNOSIS,
            phase="clarifying",
            message=question,
            answers=dict(state.answers),
            tree_id=tree.id,
            unknown_fields=dict(state.unknown_fields),
        )

    def _ready_to_diagnose(
        self, state: DiagnosisState, tree: DiagnosisTree
    ) -> TurnResult:
        unknown = {
            name: state.unknown_fields.get(name, "not provided")
            for name in tree.required_fields
            if name not in state.answers
        }
        state.status = "ready"
        return TurnResult(
            mode="diagnose",
            intent=ISSUE_DIAGNOSIS,
            enriched_query=self.build_enriched_query(tree, state),
            answers=dict(state.answers),
            tree_id=tree.id,
            phase="preliminary" if unknown else "diagnosing",
            unknown_fields=unknown,
            preliminary=bool(unknown),
            include_history=False,
        )

    def build_enriched_query(self, tree: DiagnosisTree, state: DiagnosisState) -> str:
        lines: list[str] = []
        if tree.retrieval_terms and not state.symptom_corrected:
            # A questionnaire's example T-code is not a user-reported transaction.
            lines.append(
                " ".join(
                    term for term in tree.retrieval_terms if not transaction_codes(term)
                )
            )
        lines.append(
            "Current user-reported issue (unverified)"
            if state.symptom_corrected
            else tree.intent
        )
        if state.opening_message:
            lines.append(f"Reported issue: {state.opening_message}")
        for note in state.followups:
            lines.append(f"Follow-up symptom: {note}")

        label_map = {
            "transaction": "Transaction",
            "error_message": "Error",
            "release_group": "Release Group",
            "release_code": "Release Code",
            "po_created": "PO Created",
            "po_number": "PO Number",
            "material": "Material",
            "sales_area": "Sales Area",
            "order_number": "Order Number",
            "shipping_point": "Shipping Point",
            "sales_order": "Sales Order",
            "company_code": "Company Code",
            "account": "Account",
            "user_id": "User ID",
            "su53_object": "SU53",
            "module": "Module",
            "steps_taken": "Steps Taken",
        }

        for field_name in tree.required_fields:
            value = state.answers.get(field_name)
            if not value:
                continue
            label = label_map.get(field_name, field_name.replace("_", " ").title())
            lines.append(f"{label}: {value}")

        # Include any extra collected answers not in required_fields
        for field_name, value in state.answers.items():
            if field_name in tree.required_fields:
                continue
            label = label_map.get(field_name, field_name.replace("_", " ").title())
            lines.append(f"{label}: {value}")

        return "\n".join(lines)

    def mark_completed(self, session_id: str) -> None:
        state = self.session_store.get(session_id)
        if state is None:
            return
        # The questionnaire is idle, but retain canonical details for follow-ups/corrections.
        state.status = "idle"
        state.pending_field = None

    def clear_session(self, session_id: str) -> bool:
        return self.session_store.clear(session_id)

    def delete_session(self, session_id: str) -> bool:
        return self.session_store.delete(session_id)
