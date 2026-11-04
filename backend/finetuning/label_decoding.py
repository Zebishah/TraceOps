"""Versioned finite JSON vocabulary for classifier generation, without label remapping."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory

FINITE_LABEL_POLICY = "finite-labels-v1"
# Immutable vocabulary for this policy version. A schema change needs a new policy.
CATEGORIES = ("payment", "account", "access", "data", "integration", "system", "security", "other")
PRIORITIES = ("low", "medium", "high", "critical")


class LabelTokenizer(Protocol):
    eos_token_id: int | None

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...

    def decode(self, token_ids: list[int], *, skip_special_tokens: bool) -> str: ...


@dataclass
class _Node:
    children: dict[int, "_Node"] = field(default_factory=dict)
    terminal: bool = False


class FiniteLabelDecoder:
    """Allows only token paths forming one of the 32 canonical label objects."""

    def __init__(self, tokenizer: LabelTokenizer, *, max_new_tokens: int) -> None:
        eos = tokenizer.eos_token_id
        if type(eos) is not int or eos < 0:
            raise ValueError("Finite label decoding requires one valid EOS token")
        self.eos_token_id = eos
        self.root = _Node()
        self.max_answer_tokens = 0
        for category in CATEGORIES:
            for priority in PRIORITIES:
                answer = ClassifierLabels(
                    category=IncidentCategory(category), priority=IncidentPriority(priority)
                ).model_dump_json()
                tokens = tokenizer.encode(answer, add_special_tokens=False)
                if (
                    not tokens
                    or eos in tokens
                    or any(type(token) is not int or token < 0 for token in tokens)
                    or tokenizer.decode(tokens, skip_special_tokens=False) != answer
                ):
                    raise ValueError("Tokenizer cannot round-trip the finite label vocabulary")
                if len(tokens) + 1 > max_new_tokens:
                    raise ValueError("Generation budget cannot fit every valid label plus EOS")
                self.max_answer_tokens = max(self.max_answer_tokens, len(tokens))
                node = self.root
                for token in tokens:
                    node = node.children.setdefault(token, _Node())
                if node.terminal:
                    raise ValueError("Label token paths must be unique")
                node.terminal = True

    def allowed_tokens(self, generated: Sequence[int]) -> list[int]:
        node = self.root
        for token in generated:
            child = node.children.get(token)
            if child is None:
                raise ValueError("Generated tokens left the finite label vocabulary")
            node = child
        allowed = sorted(node.children)
        if node.terminal:
            allowed.append(self.eos_token_id)
        if not allowed:
            raise ValueError("No valid continuation for classifier output")
        return allowed
