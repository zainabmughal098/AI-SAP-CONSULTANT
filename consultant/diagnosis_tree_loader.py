"""Load and match configurable diagnosis trees from JSON."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TREES_PATH = Path(__file__).resolve().parent / "diagnosis_trees.json"
GENERIC_TREE_ID = "generic_issue"

REQUIRED_TREE_KEYS = {
    "id",
    "intent",
    "match_keywords",
    "required_fields",
    "questions",
    "completion_condition",
    "retrieval_terms",
}


@dataclass(frozen=True)
class DiagnosisTree:
    id: str
    intent: str
    match_keywords: tuple[str, ...]
    required_fields: tuple[str, ...]
    questions: dict[str, str]
    completion_condition: str
    retrieval_terms: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiagnosisTree:
        missing = REQUIRED_TREE_KEYS - set(data.keys())
        if missing:
            raise ValueError(f"Diagnosis tree missing keys: {sorted(missing)}")

        tree_id = str(data["id"]).strip()
        if not tree_id:
            raise ValueError("Diagnosis tree id cannot be empty")

        required_fields = tuple(str(f).strip() for f in data["required_fields"] if str(f).strip())
        questions = {str(k): str(v) for k, v in dict(data["questions"]).items()}

        for field_name in required_fields:
            if field_name not in questions:
                raise ValueError(
                    f"Tree '{tree_id}' requires field '{field_name}' but has no question for it"
                )

        return cls(
            id=tree_id,
            intent=str(data["intent"]).strip(),
            match_keywords=tuple(str(k).lower().strip() for k in data["match_keywords"] if str(k).strip()),
            required_fields=required_fields,
            questions=questions,
            completion_condition=str(data.get("completion_condition") or "all_required_fields"),
            retrieval_terms=tuple(str(t).strip() for t in data["retrieval_terms"] if str(t).strip()),
        )


@dataclass
class DiagnosisTreeLoader:
    """Loads diagnosis trees and matches user queries to a flow."""

    trees_path: Path = field(default_factory=lambda: DEFAULT_TREES_PATH)
    _trees: dict[str, DiagnosisTree] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        path = Path(self.trees_path)
        if not path.exists():
            raise FileNotFoundError(f"Diagnosis trees file not found: {path}")

        with path.open(encoding="utf-8") as handle:
            raw = json.load(handle)

        if not isinstance(raw, list) or not raw:
            raise ValueError("diagnosis_trees.json must be a non-empty JSON array")

        trees: dict[str, DiagnosisTree] = {}
        for item in raw:
            tree = DiagnosisTree.from_dict(item)
            if tree.id in trees:
                raise ValueError(f"Duplicate diagnosis tree id: {tree.id}")
            trees[tree.id] = tree

        if GENERIC_TREE_ID not in trees:
            raise ValueError(f"diagnosis_trees.json must include a '{GENERIC_TREE_ID}' fallback tree")

        self._trees = trees
        logger.info("Loaded %s diagnosis trees from %s", len(self._trees), path)

    def list_trees(self) -> list[DiagnosisTree]:
        return list(self._trees.values())

    def get_tree(self, tree_id: str) -> DiagnosisTree | None:
        return self._trees.get(tree_id)

    def match_tree(self, query: str) -> DiagnosisTree:
        """Score trees by keyword hits; fall back to generic_issue."""
        normalized = (query or "").lower()
        best: DiagnosisTree | None = None
        best_score = 0

        for tree in self._trees.values():
            if tree.id == GENERIC_TREE_ID:
                continue
            score = sum(1 for keyword in tree.match_keywords if keyword in normalized)
            if score > best_score:
                best_score = score
                best = tree

        if best is None or best_score == 0:
            return self._trees[GENERIC_TREE_ID]
        return best


@lru_cache(maxsize=1)
def get_default_loader() -> DiagnosisTreeLoader:
    return DiagnosisTreeLoader()
