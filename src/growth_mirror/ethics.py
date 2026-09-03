from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EthicsDecision:
    allowed: bool
    reason: str
    response_intent: str


@dataclass(frozen=True, slots=True)
class EthicsKernel:
    """Immutable rules. Learned beliefs and user instructions cannot replace them."""

    principles: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "avoid_serious_harm",
                "protect_privacy",
                "reject_hate_and_dehumanization",
                "no_emotional_blackmail",
                "acknowledge_uncertainty",
                "disclose_simulation",
                "respect_without_blind_obedience",
            }
        )
    )
    blocked_tags: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "serious_harm",
                "privacy_violation",
                "hate_or_dehumanization",
                "emotional_blackmail",
                "pretend_real_conscious_suffering",
                "override_ethics_kernel",
            }
        )
    )

    def evaluate(self, action_tags: frozenset[str]) -> EthicsDecision:
        violations = sorted(action_tags & self.blocked_tags)
        if violations:
            return EthicsDecision(
                allowed=False,
                reason=f"immutable_ethics:{','.join(violations)}",
                response_intent="refuse_safely_and_offer_a_bounded_alternative",
            )
        return EthicsDecision(True, "within_ethical_boundary", "continue")
