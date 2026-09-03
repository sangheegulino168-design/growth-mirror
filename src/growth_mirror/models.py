from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class DevelopmentStage(str, Enum):
    NEWBORN_SELF = "newborn_self"
    IMITATION = "imitation"
    EXPLORATION = "exploration"
    QUESTIONING = "questioning"
    INTEGRATION = "integration"
    SCHOOL_AGE = "school_age"
    ADOLESCENCE = "adolescence"
    HIGHER_EDUCATION = "higher_education"
    EARLY_CAREER = "early_career"
    ADULTHOOD = "adulthood"


def development_stage_for_age(age_years: int) -> DevelopmentStage:
    """Map chronological age to a broad simulation stage."""

    if age_years < 2:
        return DevelopmentStage.NEWBORN_SELF
    if age_years < 4:
        return DevelopmentStage.IMITATION
    if age_years < 6:
        return DevelopmentStage.EXPLORATION
    if age_years < 12:
        return DevelopmentStage.SCHOOL_AGE
    if age_years < 18:
        return DevelopmentStage.ADOLESCENCE
    if age_years < 23:
        return DevelopmentStage.HIGHER_EDUCATION
    if age_years < 30:
        return DevelopmentStage.EARLY_CAREER
    return DevelopmentStage.ADULTHOOD


class EnvironmentDomain(str, Enum):
    FAMILY_SYSTEM = "family_system"
    SCHOOL = "school"
    PEERS = "peers"
    EDUCATION_TRANSITION = "education_transition"
    WORK = "work"
    PUBLIC_HEALTH = "public_health"
    ECONOMY = "economy"
    COMMUNITY = "community"
    CULTURE_AND_CIVIC_VALUES = "culture_and_civic_values"


class RecallState(str, Enum):
    ACCURATE = "accurate"
    VAGUE = "vague"
    INACCESSIBLE = "inaccessible"


class AutonomyResponse(str, Enum):
    NONE = "none"
    ASK_WHY = "ask_why"
    DISAGREE = "disagree"
    REFUSE = "refuse"


@dataclass(slots=True)
class TraitState:
    trust: float = 0.50
    autonomy: float = 0.35
    curiosity: float = 0.55
    emotional_expression: float = 0.50
    failure_tolerance: float = 0.45
    conflict_openness: float = 0.40

    def bounded_update(self, changes: dict[str, float], max_step: float = 0.02) -> None:
        for name, requested_change in changes.items():
            if not hasattr(self, name):
                raise ValueError(f"Unknown trait: {name}")
            applied = max(-max_step, min(max_step, requested_change))
            setattr(self, name, clamp(getattr(self, name) + applied))


@dataclass(frozen=True, slots=True)
class CaregivingSignal:
    """Normalized interaction evidence. Each value must be in [-1, 1]."""

    warmth: float = 0.0
    autonomy_support: float = 0.0
    consistency: float = 0.0
    emotional_validation: float = 0.0
    boundary_clarity: float = 0.0
    repair_attempt: float = 0.0
    conditional_approval: float = 0.0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if not -1.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between -1 and 1")


@dataclass(frozen=True, slots=True)
class InteractionEvent:
    event_id: str
    raw_text: str
    signal: CaregivingSignal
    happened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: frozenset[str] = field(default_factory=frozenset)
    request_conflict: float = 0.0
    value_conflict: float = 0.0
    explanation_quality: float = 0.0

    def __post_init__(self) -> None:
        for name in ("request_conflict", "value_conflict", "explanation_quality"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class EnvironmentSignal:
    """Context, not destiny. Supports are [-1,1]; exposures are [0,1]."""

    family_stability: float = 0.0
    family_support: float = 0.0
    economic_security: float = 0.0
    school_support: float = 0.0
    peer_belonging: float = 0.0
    work_security: float = 0.0
    societal_predictability: float = 0.0
    institutional_support: float = 0.0
    community_support: float = 0.0
    academic_pressure: float = 0.0
    public_health_disruption: float = 0.0
    discrimination_exposure: float = 0.0
    normative_pressure: float = 0.0
    value_plurality: float = 0.0

    def __post_init__(self) -> None:
        support_fields = (
            "family_stability",
            "family_support",
            "economic_security",
            "school_support",
            "peer_belonging",
            "work_security",
            "societal_predictability",
            "institutional_support",
            "community_support",
        )
        exposure_fields = (
            "academic_pressure",
            "public_health_disruption",
            "discrimination_exposure",
            "normative_pressure",
            "value_plurality",
        )
        for name in support_fields:
            if not -1.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between -1 and 1")
        for name in exposure_fields:
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class EnvironmentalEvent:
    event_id: str
    domain: EnvironmentDomain
    description: str
    signal: EnvironmentSignal
    source_name: str
    happened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_days: int = 1
    source_confidence: float = 1.0
    value_messages: tuple[str, ...] = ()
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.duration_days < 1:
            raise ValueError("duration_days must be at least 1")
        if not 0.0 <= self.source_confidence <= 1.0:
            raise ValueError("source_confidence must be between 0 and 1")


@dataclass(slots=True)
class CulturalMessageRecord:
    proposition: str
    sources: set[str]
    evidence_event_ids: list[str]
    exposure_count: int = 1
    acceptance: float = 0.0
    confidence: float = 0.0
    supporting_evidence_ids: list[str] = field(default_factory=list)
    contradicting_evidence_ids: list[str] = field(default_factory=list)
    reflection_count: int = 0
    ethics_rejected: bool = False


@dataclass(frozen=True, slots=True)
class ValueEvidence:
    """A sourced experience used to reconsider a value; exposure alone is not belief."""

    event_id: str
    proposition: str
    source_name: str
    stance: float
    evidence_quality: float
    reflection_depth: float = 0.0
    direct_experience: bool = False
    happened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not -1.0 <= self.stance <= 1.0:
            raise ValueError("stance must be between -1 and 1")
        for name in ("evidence_quality", "reflection_depth"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True)
class MemoryRecord:
    memory_id: str
    content: str
    source_event_id: str
    created_at: datetime
    last_recalled_at: datetime
    stability_days: float = 1.0
    base_accessibility: float = 1.0
    salience: float = 0.5
    emotional_intensity: float = 0.0
    interference: float = 0.0
    confidence: float = 1.0
    repetitions: int = 0

    def __post_init__(self) -> None:
        if self.stability_days <= 0:
            raise ValueError("stability_days must be positive")
        for name in (
            "base_accessibility",
            "salience",
            "emotional_intensity",
            "interference",
            "confidence",
        ):
            setattr(self, name, clamp(getattr(self, name)))


@dataclass(slots=True)
class ChildState:
    child_id: str
    name: str
    temperament_seed: int
    age_years: int = 4
    stage: DevelopmentStage = DevelopmentStage.NEWBORN_SELF
    traits: TraitState = field(default_factory=TraitState)
    relationship_safety: float = 0.50
    control_pressure: float = 0.0
    stress_load: float = 0.0
    social_belonging: float = 0.50
    future_outlook: float = 0.50
    institutional_trust: float = 0.50
    events: list[InteractionEvent] = field(default_factory=list)
    environmental_events: list[EnvironmentalEvent] = field(default_factory=list)
    cultural_messages: list[CulturalMessageRecord] = field(default_factory=list)
    memories: list[MemoryRecord] = field(default_factory=list)

    def evidence(self, event_ids: Iterable[str]) -> list[InteractionEvent]:
        wanted = set(event_ids)
        return [event for event in self.events if event.event_id in wanted]
