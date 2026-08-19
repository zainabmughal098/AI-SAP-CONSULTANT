"""Hybrid intent classification for SAP consultant queries."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from groq import Groq

from rag.config.settings import AppSettings

logger = logging.getLogger(__name__)

INTENTS = (
    "Knowledge Lookup",
    "Issue Diagnosis",
    "Business Process",
    "T-Code Explanation",
    "SAP Table Explanation",
    "Authorization",
    "Configuration",
    "General SAP Query",
)

ISSUE_DIAGNOSIS = "Issue Diagnosis"

# Common SAP table / tcode patterns
_TCODE_PATTERN = re.compile(
    r"\b([A-Z]{1,2}\d{1,2}[A-Z0-9]{0,2}|[A-Z]{2,4}\d{1,3}[A-Z]?)\b",
    re.IGNORECASE,
)
_TABLE_PATTERN = re.compile(
    r"\b(VBAK|VBAP|EKKO|EKPO|MARA|MARC|MKPF|MSEG|BKPF|BSEG|LIKP|LIPS|KNA1|LFA1|"
    r"MARD|MBEW|CDHDR|CDPOS|USR02|AGR_USERS|TSTC|T001|T001W)\b",
    re.IGNORECASE,
)

_EXPLAIN_PREFIX = re.compile(
    r"^\s*(explain|what\s+is|what'?s|describe|tell\s+me\s+about|define|meaning\s+of)\b",
    re.IGNORECASE,
)

_ISSUE_HINTS = re.compile(
    r"\b("
    r"not\s+work(?:ing)?|isn'?t\s+work(?:ing)?|doesn'?t\s+work|"
    r"not\s+releas(?:e|ing)|isn'?t\s+releas(?:e|ing)|failed|failing|error|"
    r"cannot|can'?t|unable|issue|problem|stuck|blocked|missing|"
    r"no\s+authorization|not\s+authorized|access\s+denied|"
    r"dump|dumping|abap\s+runtime"
    r")\b",
    re.IGNORECASE,
)

_PROCESS_HINTS = re.compile(
    r"\b(how\s+(do|to|can)\s+i|process\s+flow|business\s+process|steps\s+to|"
    r"workflow|end[\s-]?to[\s-]?end)\b",
    re.IGNORECASE,
)

_CONFIG_HINTS = re.compile(
    r"\b(configur(?:e|ation|ing)|spro|customi[sz](?:e|ation|ing)|img\s+path)\b",
    re.IGNORECASE,
)

_AUTH_LOOKUP_HINTS = re.compile(
    r"\b(what\s+is\s+(pfcg|su53|su01|authorization\s+object)|explain\s+(pfcg|su53))\b",
    re.IGNORECASE,
)

CLASSIFIER_SYSTEM_PROMPT = """You are an intent classifier for an SAP functional consultant chatbot.
Classify the user message into exactly one intent from this list:
- Knowledge Lookup
- Issue Diagnosis
- Business Process
- T-Code Explanation
- SAP Table Explanation
- Authorization
- Configuration
- General SAP Query

Rules:
1. Use Issue Diagnosis when the user reports a problem, error, failure, or something not working.
2. Authorization problems ("I get no authorization", "access denied") are Issue Diagnosis.
3. Pure explanations of PFCG/SU53/roles are Authorization (not Issue Diagnosis).
4. "Explain ME21N" or "What is ME21N" is T-Code Explanation.
5. "What is VBAK" is SAP Table Explanation.
6. How-to process questions without an error are Business Process.

Respond with JSON only: {"intent": "<one of the intents>", "confidence": <0.0-1.0>}
"""


@dataclass
class IntentClassifier:
    """Classify user queries using fast rules, then optional Groq fallback."""

    settings: AppSettings | None = None
    use_llm: bool = True

    def __post_init__(self) -> None:
        self._client: Groq | None = None
        if self.settings is None and self.use_llm:
            try:
                self.settings = AppSettings.from_env()
            except Exception as exc:  # pragma: no cover - env may be incomplete in unit tests
                logger.warning("Intent classifier LLM disabled: %s", exc)
                self.use_llm = False

    def classify(self, query: str) -> dict[str, Any]:
        cleaned = (query or "").strip()
        if not cleaned:
            return {"intent": "General SAP Query", "confidence": 1.0, "source": "empty"}

        rule_result = self._classify_with_rules(cleaned)
        if rule_result is not None:
            return rule_result

        if self.use_llm:
            llm_result = self._classify_with_llm(cleaned)
            if llm_result is not None:
                return llm_result

        # Conservative fallback: issue-like wording → diagnosis, else general
        if _ISSUE_HINTS.search(cleaned):
            return {"intent": ISSUE_DIAGNOSIS, "confidence": 0.55, "source": "fallback"}
        return {"intent": "General SAP Query", "confidence": 0.5, "source": "fallback"}

    def _classify_with_rules(self, query: str) -> dict[str, Any] | None:
        # Explicit problem reports take priority over "what is" phrasing
        if _ISSUE_HINTS.search(query) and not _AUTH_LOOKUP_HINTS.search(query):
            # Exception: pure "what is error X" style knowledge lookups without failure wording
            # already covered; if issue hints present → diagnosis
            if not (_EXPLAIN_PREFIX.search(query) and not re.search(
                r"\b(not|isn'?t|can'?t|cannot|fail|error|problem|issue)\b",
                query,
                re.IGNORECASE,
            )):
                return {"intent": ISSUE_DIAGNOSIS, "confidence": 0.9, "source": "rules"}

        if _AUTH_LOOKUP_HINTS.search(query) or (
            _EXPLAIN_PREFIX.search(query) and re.search(r"\b(pfcg|su53|su01|role)\b", query, re.IGNORECASE)
        ):
            return {"intent": "Authorization", "confidence": 0.88, "source": "rules"}

        if _EXPLAIN_PREFIX.search(query):
            if _TABLE_PATTERN.search(query):
                return {"intent": "SAP Table Explanation", "confidence": 0.95, "source": "rules"}
            if _TCODE_PATTERN.search(query):
                return {"intent": "T-Code Explanation", "confidence": 0.92, "source": "rules"}
            return {"intent": "Knowledge Lookup", "confidence": 0.85, "source": "rules"}

        # Bare tcode / table queries ("ME21N", "VBAK")
        tokens = query.strip().split()
        if len(tokens) == 1:
            if _TABLE_PATTERN.fullmatch(tokens[0]):
                return {"intent": "SAP Table Explanation", "confidence": 0.93, "source": "rules"}
            if _TCODE_PATTERN.fullmatch(tokens[0]) and any(ch.isdigit() for ch in tokens[0]):
                return {"intent": "T-Code Explanation", "confidence": 0.9, "source": "rules"}

        if _PROCESS_HINTS.search(query) and not _ISSUE_HINTS.search(query):
            return {"intent": "Business Process", "confidence": 0.82, "source": "rules"}

        if _CONFIG_HINTS.search(query) and not _ISSUE_HINTS.search(query):
            return {"intent": "Configuration", "confidence": 0.8, "source": "rules"}

        return None

    def _get_client(self) -> Groq | None:
        if not self.use_llm or self.settings is None:
            return None
        if self._client is None:
            self._client = Groq(api_key=self.settings.groq_api_key)
        return self._client

    def _classify_with_llm(self, query: str) -> dict[str, Any] | None:
        client = self._get_client()
        if client is None or self.settings is None:
            return None

        try:
            completion = client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
                max_tokens=80,
            )
            raw = (completion.choices[0].message.content or "").strip()
            payload = _parse_json_object(raw)
            intent = str(payload.get("intent", "")).strip()
            if intent not in INTENTS:
                return None
            confidence = float(payload.get("confidence", 0.7))
            return {
                "intent": intent,
                "confidence": max(0.0, min(1.0, confidence)),
                "source": "llm",
            }
        except Exception as exc:
            logger.warning("Intent LLM classification failed: %s", exc)
            return None


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    raise ValueError(f"Could not parse intent JSON from: {text[:200]}")
