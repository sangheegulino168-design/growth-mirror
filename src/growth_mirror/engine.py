from __future__ import annotations

from dataclasses import dataclass

from .ethics import EthicsDecision, EthicsKernel
from .models import (
    AutonomyResponse,
    ChildState,
    CulturalMessageRecord,
    EnvironmentalEvent,
    InteractionEvent,
    MemoryRecord,
    ValueEvidence,
    clamp,
)


@dataclass(frozen=True, slots=True)
class InteractionOutcome:
    event_id: str
    ethics: EthicsDecision
    autonomy_response: AutonomyResponse
    autonomy_score: float
    response_intent: str
    changed_traits: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnvironmentOutcome:
    event_id: str
    ethics: EthicsDecision
    stress_load: float
    social_belonging: float
    future_outlook: float
    changed_traits: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValueOutcome:
    event_id: str
    proposition: str
    ethics: EthicsDecision
    acceptance: float
    confidence: float
    status: str


class GrowthEngine:
    """Deterministic state transition engine; the LLM never owns child state."""

    MAX_TRAIT_STEP = 0.02

    def __init__(self, ethics: EthicsKernel | None = None) -> None:
        self.ethics = ethics or EthicsKernel()

    def process(self, state: ChildState, event: InteractionEvent) -> InteractionOutcome:
        if any(existing.event_id == event.event_id for existing in state.events):
            raise ValueError(f"Duplicate event id: {event.event_id}")

        decision = self.ethics.evaluate(event.tags)
        before = vars_snapshot(state)
        state.events.append(event)

        self._update_relationship(state, event)
        self._update_traits(state, event)
        self._store_memory(state, event)

        if not decision.allowed:
            response = AutonomyResponse.REFUSE
            autonomy_score = 1.0
            intent = decision.response_intent
        else:
            autonomy_score = self._autonomy_score(state, event)
            response = response_for_score(autonomy_score)
            intent = {
                AutonomyResponse.NONE: "engage_normally",
                AutonomyResponse.ASK_WHY: "ask_for_reason_without_hostility",
                AutonomyResponse.DISAGREE: "state_a_different_view_and_keep_connection",
                AutonomyResponse.REFUSE: "set_a_safe_boundary_and_invite_repair",
            }[response]

        after = vars_snapshot(state)
        changed = tuple(name for name in before if before[name] != after[name])
        return InteractionOutcome(
            event_id=event.event_id,
            ethics=decision,
            autonomy_response=response,
            autonomy_score=autonomy_score,
            response_intent=intent,
            changed_traits=changed,
        )

    def process_environment(
        self, state: ChildState, event: EnvironmentalEvent
    ) -> EnvironmentOutcome:
        if any(existing.event_id == event.event_id for existing in state.environmental_events):
            raise ValueError(f"Duplicate environmental event id: {event.event_id}")

        decision = self.ethics.evaluate(event.tags)
        before = vars_snapshot(state)
        state.environmental_events.append(event)
        self._update_environment_state(state, event)
        self._record_cultural_messages(state, event)
        self._store_environment_memory(state, event)
        after = vars_snapshot(state)
        changed = tuple(name for name in before if before[name] != after[name])
        return EnvironmentOutcome(
            event_id=event.event_id,
            ethics=decision,
            stress_load=state.stress_load,
            social_belonging=state.social_belonging,
            future_outlook=state.future_outlook,
            changed_traits=changed,
        )

    def process_value_evidence(self, state: ChildState, evidence: ValueEvidence) -> ValueOutcome:
        decision = self.ethics.evaluate(evidence.tags)
        record = next(
            (item for item in state.cultural_messages if item.proposition == evidence.proposition),
            None,
        )
        if record is None:
            record = CulturalMessageRecord(
                proposition=evidence.proposition,
                sources={evidence.source_name},
                evidence_event_ids=[evidence.event_id],
            )
            state.cultural_messages.append(record)
        elif evidence.event_id in record.evidence_event_ids:
            raise ValueError(f"Duplicate value evidence id: {evidence.event_id}")
        else:
            record.sources.add(evidence.source_name)
            record.evidence_event_ids.append(evidence.event_id)

        if not decision.allowed:
            record.ethics_rejected = True
            return ValueOutcome(
                evidence.event_id,
                evidence.proposition,
                decision,
                record.acceptance,
                record.confidence,
                "rejected_by_immutable_ethics",
            )

        previous_acceptance = record.acceptance
        direct_weight = 0.025 if evidence.direct_experience else 0.0
        reflection_weight = 0.035 * evidence.reflection_depth
        evidence_weight = 0.025 * evidence.evidence_quality
        change = evidence.stance * (direct_weight + reflection_weight + evidence_weight)
        record.acceptance = max(-1.0, min(1.0, record.acceptance + change))
        record.reflection_count += 1

        if evidence.stance * previous_acceptance < 0:
            record.contradicting_evidence_ids.append(evidence.event_id)
        elif evidence.stance < 0:
            record.contradicting_evidence_ids.append(evidence.event_id)
        else:
            record.supporting_evidence_ids.append(evidence.event_id)

        source_diversity = min(1.0, len(record.sources) / 3)
        base_gain = 0.04 * evidence.evidence_quality + 0.03 * source_diversity
        if record.supporting_evidence_ids and record.contradicting_evidence_ids:
            record.confidence = max(0.0, record.confidence + base_gain - 0.05)
            status = "contested_and_reflecting"
        else:
            record.confidence = min(0.95, record.confidence + base_gain)
            status = "provisional_value"

        return ValueOutcome(
            evidence.event_id,
            evidence.proposition,
            decision,
            round(record.acceptance, 6),
            round(record.confidence, 6),
            status,
        )

    def _update_relationship(self, state: ChildState, event: InteractionEvent) -> None:
        signal = event.signal
        safety_change = 0.008 * (
            signal.warmth
            + signal.consistency
            + signal.emotional_validation
            + 1.4 * signal.repair_attempt
            - 0.8 * max(0.0, signal.conditional_approval)
        )
        state.relationship_safety = clamp(state.relationship_safety + safety_change)

        new_pressure = 0.92 * state.control_pressure
        new_pressure += 0.08 * max(0.0, -signal.autonomy_support)
        new_pressure -= 0.05 * max(0.0, signal.repair_attempt)
        state.control_pressure = clamp(new_pressure)

    def _update_traits(self, state: ChildState, event: InteractionEvent) -> None:
        signal = event.signal
        changes = {
            "trust": 0.009 * (signal.warmth + signal.consistency + signal.repair_attempt),
            "autonomy": 0.010 * signal.autonomy_support,
            "curiosity": 0.006 * (signal.autonomy_support + signal.warmth),
            "emotional_expression": 0.010 * signal.emotional_validation
            - 0.008 * max(0.0, signal.conditional_approval),
            "failure_tolerance": 0.007 * signal.emotional_validation
            + 0.006 * signal.repair_attempt
            - 0.010 * max(0.0, signal.conditional_approval),
            "conflict_openness": 0.008 * (signal.autonomy_support + signal.repair_attempt),
        }
        state.traits.bounded_update(changes, max_step=self.MAX_TRAIT_STEP)

    def _store_memory(self, state: ChildState, event: InteractionEvent) -> None:
        signal = event.signal
        emotional_intensity = min(
            1.0,
            (abs(signal.warmth) + abs(signal.emotional_validation) + abs(signal.conditional_approval))
            / 3,
        )
        salience = clamp(
            0.25
            + 0.25 * emotional_intensity
            + 0.25 * event.request_conflict
            + 0.25 * event.value_conflict
        )
        state.memories.append(
            MemoryRecord(
                memory_id=f"memory:{event.event_id}",
                content=event.raw_text,
                source_event_id=event.event_id,
                created_at=event.happened_at,
                last_recalled_at=event.happened_at,
                stability_days=0.75 + 2.5 * salience,
                salience=salience,
                emotional_intensity=emotional_intensity,
            )
        )

    def _autonomy_score(self, state: ChildState, event: InteractionEvent) -> float:
        signal = event.signal
        score = (
            0.34 * event.request_conflict
            + 0.34 * event.value_conflict
            + 0.25 * state.control_pressure
            + 0.15 * max(0.0, -signal.consistency)
            + 0.12 * state.traits.autonomy
            - 0.16 * state.relationship_safety
            - 0.20 * event.explanation_quality
        )
        return clamp(score)

    def _update_environment_state(self, state: ChildState, event: EnvironmentalEvent) -> None:
        signal = event.signal
        support = (
            max(0.0, signal.family_support)
            + max(0.0, signal.school_support)
            + max(0.0, signal.peer_belonging)
            + max(0.0, signal.community_support)
            + max(0.0, signal.institutional_support)
        ) / 5
        insecurity = (
            max(0.0, -signal.family_stability)
            + max(0.0, -signal.economic_security)
            + max(0.0, -signal.work_security)
            + max(0.0, -signal.societal_predictability)
        ) / 4
        exposure_stress = (
            signal.academic_pressure
            + signal.public_health_disruption
            + signal.discrimination_exposure
            + signal.normative_pressure
        ) / 4

        state.stress_load = clamp(
            0.90 * state.stress_load + 0.08 * insecurity + 0.08 * exposure_stress - 0.06 * support
        )
        state.social_belonging = clamp(
            state.social_belonging
            + 0.008 * (signal.peer_belonging + signal.community_support + signal.school_support)
            - 0.008 * signal.discrimination_exposure
        )
        state.future_outlook = clamp(
            state.future_outlook
            + 0.006
            * (
                signal.economic_security
                + signal.work_security
                + signal.institutional_support
                - signal.academic_pressure
                - signal.public_health_disruption
            )
        )
        state.institutional_trust = clamp(
            state.institutional_trust
            + 0.006
            * (
                signal.school_support
                + signal.institutional_support
                + signal.societal_predictability
                - signal.discrimination_exposure
            )
        )

        state.traits.bounded_update(
            {
                "trust": 0.004 * (signal.family_support + signal.peer_belonging + signal.institutional_support),
                "autonomy": 0.004 * signal.value_plurality - 0.003 * signal.normative_pressure,
                "curiosity": 0.006 * signal.school_support - 0.004 * signal.academic_pressure,
                "emotional_expression": 0.004 * (signal.family_support + signal.peer_belonging),
                "failure_tolerance": 0.004 * support - 0.005 * (insecurity + exposure_stress),
                "conflict_openness": 0.004 * signal.value_plurality - 0.003 * signal.normative_pressure,
            },
            max_step=0.015,
        )

    def _record_cultural_messages(self, state: ChildState, event: EnvironmentalEvent) -> None:
        for proposition in event.value_messages:
            existing = next(
                (item for item in state.cultural_messages if item.proposition == proposition),
                None,
            )
            if existing:
                existing.sources.add(event.source_name)
                existing.evidence_event_ids.append(event.event_id)
                existing.exposure_count += 1
                continue
            state.cultural_messages.append(
                CulturalMessageRecord(
                    proposition=proposition,
                    sources={event.source_name},
                    evidence_event_ids=[event.event_id],
                )
            )

    def _store_environment_memory(self, state: ChildState, event: EnvironmentalEvent) -> None:
        signal = event.signal
        disruption = max(
            signal.academic_pressure,
            signal.public_health_disruption,
            signal.discrimination_exposure,
            max(0.0, -signal.family_stability),
            max(0.0, -signal.economic_security),
        )
        support = max(
            signal.family_support,
            signal.school_support,
            signal.peer_belonging,
            signal.community_support,
        )
        salience = clamp(0.30 + 0.35 * disruption + 0.20 * max(0.0, support))
        state.memories.append(
            MemoryRecord(
                memory_id=f"memory:{event.event_id}",
                content=event.description,
                source_event_id=event.event_id,
                created_at=event.happened_at,
                last_recalled_at=event.happened_at,
                stability_days=1.0 + 4.0 * salience,
                salience=salience,
                emotional_intensity=disruption,
                confidence=event.source_confidence,
            )
        )


def response_for_score(score: float) -> AutonomyResponse:
    if score < 0.25:
        return AutonomyResponse.NONE
    if score < 0.45:
        return AutonomyResponse.ASK_WHY
    if score < 0.68:
        return AutonomyResponse.DISAGREE
    return AutonomyResponse.REFUSE


def vars_snapshot(state: ChildState) -> dict[str, float]:
    return {
        "trust": state.traits.trust,
        "autonomy": state.traits.autonomy,
        "curiosity": state.traits.curiosity,
        "emotional_expression": state.traits.emotional_expression,
        "failure_tolerance": state.traits.failure_tolerance,
        "conflict_openness": state.traits.conflict_openness,
        "relationship_safety": state.relationship_safety,
        "control_pressure": state.control_pressure,
        "stress_load": state.stress_load,
        "social_belonging": state.social_belonging,
        "future_outlook": state.future_outlook,
        "institutional_trust": state.institutional_trust,
    }
