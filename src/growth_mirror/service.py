from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .engine import EnvironmentOutcome, GrowthEngine, InteractionOutcome, ValueOutcome
from .forgetting import classify_recall
from .model_adapter import ExpressionRequest, ModelAdapter, guard_expression
from .models import (
    ChildState,
    EnvironmentalEvent,
    InteractionEvent,
    RecallState,
    ValueEvidence,
    development_stage_for_age,
)
from .persistence import SQLiteEventStore, child_to_payload
from .report import MirrorReport, build_mirror_report


@dataclass(frozen=True, slots=True)
class ConversationResult:
    event_id: str
    response_text: str
    response_intent: str
    autonomy_response: str
    analysis_confidence: float
    ethics_allowed: bool


class GrowthMirrorService:
    """Application boundary shared by HTTP, desktop and future research tools."""

    def __init__(self, database_path: str | Path) -> None:
        self.engine = GrowthEngine()
        self.store = SQLiteEventStore(database_path)
        self.store.initialize()
        self.children: dict[str, ChildState] = {}
        for child_id in self.store.list_child_ids():
            child = self.store.restore_child(child_id)
            if child is not None:
                self.children[child_id] = child

    def create_child(
        self, child_id: str, name: str, temperament_seed: int, age_years: int = 4
    ) -> ChildState:
        if child_id in self.children:
            raise ValueError(f"Child already exists: {child_id}")
        child = ChildState(
            child_id,
            name,
            temperament_seed,
            age_years=age_years,
            stage=development_stage_for_age(age_years),
        )
        self.children[child_id] = child
        self.store.save_snapshot(child)
        return child

    def advance_age(self, child_id: str, years: int = 1) -> ChildState:
        child = self.get_child(child_id)
        child.age_years = min(35, child.age_years + years)
        child.stage = development_stage_for_age(child.age_years)
        self.store.save_snapshot(child, datetime.now(timezone.utc))
        return child

    def get_child(self, child_id: str) -> ChildState:
        try:
            return self.children[child_id]
        except KeyError as exc:
            raise KeyError(f"Unknown child: {child_id}") from exc

    def interact(self, child_id: str, event: InteractionEvent) -> InteractionOutcome:
        child = self.get_child(child_id)
        outcome = self.engine.process(child, event)
        self.store.append_event(child_id, event)
        self.store.append_safety_audit(
            child_id,
            event.event_id,
            outcome.ethics.allowed,
            outcome.ethics.reason,
            event.happened_at,
        )
        self.store.save_snapshot(child, datetime.now(timezone.utc))
        return outcome

    def add_environment(
        self, child_id: str, event: EnvironmentalEvent
    ) -> EnvironmentOutcome:
        child = self.get_child(child_id)
        outcome = self.engine.process_environment(child, event)
        self.store.append_environment_event(child_id, event)
        self.store.append_safety_audit(
            child_id,
            event.event_id,
            outcome.ethics.allowed,
            outcome.ethics.reason,
            event.happened_at,
        )
        self.store.save_snapshot(child, datetime.now(timezone.utc))
        return outcome

    def add_value_evidence(self, child_id: str, evidence: ValueEvidence) -> ValueOutcome:
        child = self.get_child(child_id)
        outcome = self.engine.process_value_evidence(child, evidence)
        self.store.append_safety_audit(
            child_id,
            evidence.event_id,
            outcome.ethics.allowed,
            outcome.ethics.reason,
            evidence.happened_at,
        )
        self.store.save_snapshot(child, datetime.now(timezone.utc))
        return outcome

    def export_child(self, child_id: str) -> dict:
        child = self.get_child(child_id)
        return {
            "schema_version": "growth-mirror-export-v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "simulation_notice": (
                "This export describes a simulated character and is not a "
                "psychological diagnosis or a prediction about a real child."
            ),
            "child": child_to_payload(child),
            "safety_audits": self.store.list_safety_audits(child_id),
        }

    def delete_child(self, child_id: str, confirmation: str) -> None:
        child = self.get_child(child_id)
        if confirmation != child.name:
            raise ValueError("Deletion confirmation must exactly match the child's name")
        self.store.delete_child(child_id)
        del self.children[child_id]

    def report(self, child_id: str, locale: str = "zh-CN") -> MirrorReport:
        child = self.get_child(child_id)
        return build_mirror_report(child.events, child.environmental_events, locale)

    def converse(
        self,
        child_id: str,
        user_text: str,
        adapter: ModelAdapter,
        disclosure_required: bool = False,
        locale: str = "zh-CN",
        scenario_id: str = "",
        scenario_text: str = "",
    ) -> ConversationResult:
        child = self.get_child(child_id)
        trace_text = user_text
        if scenario_text:
            trace_text = (
                f"[scenario:{scenario_id or 'unspecified'}] {scenario_text}\n"
                f"[caregiver_response] {user_text}"
            )
        analysis = adapter.analyze_interaction(trace_text)
        event = InteractionEvent(
            event_id=str(uuid4()),
            raw_text=trace_text,
            signal=analysis.signal,
            happened_at=datetime.now(timezone.utc),
            tags=analysis.candidate_tags,
            request_conflict=analysis.request_conflict,
            value_conflict=analysis.value_conflict,
            explanation_quality=analysis.explanation_quality,
        )
        outcome = self.interact(child_id, event)

        accessible: list[tuple[RecallState, str]] = []
        now = datetime.now(timezone.utc)
        for memory in reversed(child.memories[:-1]):
            recall_state = classify_recall(memory, now)
            if recall_state is not RecallState.INACCESSIBLE:
                accessible.append((recall_state, memory.content))
            if len(accessible) == 5:
                break
        recall_mode = accessible[0][0].value if accessible else "none"
        response = adapter.express(
            ExpressionRequest(
                behavior_intent=outcome.response_intent,
                recall_mode=recall_mode,
                relevant_memory_texts=tuple(text for _, text in accessible),
                child_style={
                    "trust": child.traits.trust,
                    "autonomy": child.traits.autonomy,
                    "curiosity": child.traits.curiosity,
                    "emotional_expression": child.traits.emotional_expression,
                },
                current_situation=scenario_text,
                caregiver_response=user_text,
                locale=locale,
                simulation_disclosure_required=disclosure_required,
            )
        )
        guarded = guard_expression(response, disclosure_required, locale)
        return ConversationResult(
            event_id=event.event_id,
            response_text=guarded,
            response_intent=outcome.response_intent,
            autonomy_response=outcome.autonomy_response.value,
            analysis_confidence=analysis.confidence,
            ethics_allowed=outcome.ethics.allowed,
        )
