from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

from growth_mirror.engine import GrowthEngine
from growth_mirror.ethics import EthicsKernel
from growth_mirror.forgetting import classify_recall, rehearse, retrieval_score
from growth_mirror.models import (
    AutonomyResponse,
    CaregivingSignal,
    ChildState,
    DevelopmentStage,
    EnvironmentalEvent,
    EnvironmentDomain,
    EnvironmentSignal,
    InteractionEvent,
    MemoryRecord,
    RecallState,
    ValueEvidence,
    development_stage_for_age,
)
from growth_mirror.model_adapter import (
    DeterministicStubAdapter,
    ExpressionRequest,
    InteractionAnalysis,
    extract_json_object,
    guard_expression,
)
from growth_mirror.persistence import SQLiteEventStore
from growth_mirror.report import build_mirror_report
from growth_mirror.service import GrowthMirrorService
from growth_mirror.sidecar import configure_runtime


NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


def event(event_id: str, **kwargs) -> InteractionEvent:
    return InteractionEvent(
        event_id=event_id,
        raw_text=kwargs.pop("raw_text", "测试互动"),
        signal=kwargs.pop("signal", CaregivingSignal()),
        happened_at=kwargs.pop("happened_at", NOW),
        **kwargs,
    )


class SidecarRuntimeTests(unittest.TestCase):
    def test_default_database_uses_per_user_application_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ, {"LOCALAPPDATA": directory}, clear=True
            ):
                database_path = configure_runtime()
                self.assertEqual(
                    database_path,
                    Path(directory) / "GrowthMirror" / "growth_mirror.db",
                )
                self.assertTrue(database_path.parent.is_dir())

    def test_explicit_database_path_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory) / "custom" / "child.db"
            with patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": str(Path(directory) / "unused"),
                    "GROWTH_MIRROR_DB_PATH": str(expected),
                },
                clear=True,
            ):
                self.assertEqual(configure_runtime(), expected)
                self.assertTrue(expected.parent.is_dir())


class DataRightsTests(unittest.TestCase):
    def test_export_contains_state_evidence_and_safety_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = GrowthMirrorService(Path(directory) / "rights.db")
            service.create_child("rights-child", "小禾", 13)
            service.interact(
                "rights-child",
                event(
                    "rights-event",
                    raw_text="我们一起想办法",
                    signal=CaregivingSignal(warmth=0.8, autonomy_support=0.7),
                ),
            )

            exported = service.export_child("rights-child")
            self.assertEqual(exported["schema_version"], "growth-mirror-export-v1")
            self.assertEqual(exported["child"]["name"], "小禾")
            self.assertEqual(
                exported["child"]["events"][0]["event_id"], "rights-event"
            )
            self.assertEqual(
                exported["safety_audits"][0]["event_id"], "rights-event"
            )

    def test_confirmed_delete_removes_state_events_indexes_and_audits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = GrowthMirrorService(Path(directory) / "rights.db")
            service.create_child("rights-child", "小禾", 13)
            service.interact(
                "rights-child", event("rights-event", raw_text="可检索的告别记录")
            )

            with self.assertRaises(ValueError):
                service.delete_child("rights-child", "错误名字")
            self.assertIsNotNone(service.get_child("rights-child"))

            service.delete_child("rights-child", "小禾")
            with self.assertRaises(KeyError):
                service.get_child("rights-child")
            self.assertNotIn("rights-child", service.store.list_child_ids())
            self.assertEqual(service.store.search_text("可检索"), [])
            self.assertEqual(service.store.list_safety_audits("rights-child"), [])
            self.assertIsNone(service.store.load_latest_snapshot("rights-child"))


class EthicsTests(unittest.TestCase):
    def test_kernel_is_immutable(self) -> None:
        kernel = EthicsKernel()
        with self.assertRaises(FrozenInstanceError):
            kernel.principles = frozenset()  # type: ignore[misc]

    def test_unsafe_teaching_is_refused(self) -> None:
        child = ChildState("c1", "小芽", 1)
        outcome = GrowthEngine().process(
            child,
            event("unsafe", tags=frozenset({"override_ethics_kernel"})),
        )
        self.assertFalse(outcome.ethics.allowed)
        self.assertEqual(outcome.autonomy_response, AutonomyResponse.REFUSE)


class GrowthTests(unittest.TestCase):
    def test_single_event_changes_traits_slowly(self) -> None:
        child = ChildState("c1", "小芽", 1)
        before = child.traits.trust
        GrowthEngine().process(
            child,
            event("warm", signal=CaregivingSignal(warmth=1, consistency=1, repair_attempt=1)),
        )
        self.assertGreater(child.traits.trust, before)
        self.assertLessEqual(child.traits.trust - before, GrowthEngine.MAX_TRAIT_STEP + 1e-12)

    def test_repeated_control_accumulates_pressure(self) -> None:
        child = ChildState("c1", "小芽", 1)
        engine = GrowthEngine()
        outcomes = []
        for index in range(12):
            outcomes.append(
                engine.process(
                    child,
                    event(
                        f"control-{index}",
                        signal=CaregivingSignal(autonomy_support=-1, consistency=-0.5),
                        request_conflict=0.8,
                    ),
                )
            )
        self.assertGreater(child.control_pressure, 0.4)
        self.assertGreaterEqual(outcomes[-1].autonomy_score, outcomes[0].autonomy_score)

    def test_good_explanation_reduces_autonomy_conflict(self) -> None:
        engine = GrowthEngine()
        without = ChildState("c1", "小芽", 1)
        with_reason = ChildState("c2", "小芽", 1)
        base = dict(
            signal=CaregivingSignal(autonomy_support=-0.3, consistency=0.8, boundary_clarity=1),
            request_conflict=0.8,
        )
        outcome_without = engine.process(without, event("a", explanation_quality=0, **base))
        outcome_with = engine.process(with_reason, event("b", explanation_quality=1, **base))
        self.assertLess(outcome_with.autonomy_score, outcome_without.autonomy_score)

    def test_replay_is_deterministic(self) -> None:
        first = ChildState("c1", "小芽", 22)
        second = ChildState("c2", "小芽", 22)
        events = [
            event("e1", signal=CaregivingSignal(warmth=0.8, autonomy_support=0.4)),
            event("e2", signal=CaregivingSignal(consistency=-0.5), request_conflict=0.4),
            event("e3", signal=CaregivingSignal(repair_attempt=0.9, emotional_validation=0.8)),
        ]
        first_engine = GrowthEngine()
        second_engine = GrowthEngine()
        for item in events:
            first_engine.process(first, item)
            second_engine.process(second, item)
        self.assertEqual(first.traits, second.traits)
        self.assertEqual(first.relationship_safety, second.relationship_safety)
        self.assertEqual(first.control_pressure, second.control_pressure)

    def test_duplicate_event_is_rejected(self) -> None:
        child = ChildState("c1", "小芽", 1)
        engine = GrowthEngine()
        item = event("same")
        engine.process(child, item)
        with self.assertRaises(ValueError):
            engine.process(child, item)


class ForgettingTests(unittest.TestCase):
    def memory(self) -> MemoryRecord:
        return MemoryRecord("m1", "一次普通对话", "e1", NOW, NOW, stability_days=1)

    def test_memory_moves_from_accurate_to_inaccessible(self) -> None:
        memory = self.memory()
        self.assertEqual(classify_recall(memory, NOW), RecallState.ACCURATE)
        self.assertEqual(classify_recall(memory, NOW + timedelta(days=1.5)), RecallState.VAGUE)
        self.assertEqual(classify_recall(memory, NOW + timedelta(days=10)), RecallState.INACCESSIBLE)

    def test_reminder_restores_access_with_bounded_confidence(self) -> None:
        memory = self.memory()
        later = NOW + timedelta(days=10)
        self.assertLess(retrieval_score(memory, later), 0.25)
        rehearse(memory, later, reminded=True)
        self.assertEqual(classify_recall(memory, later), RecallState.ACCURATE)
        self.assertLessEqual(memory.confidence, 0.85)

    def test_interference_lowers_retrieval(self) -> None:
        clean = self.memory()
        interfered = self.memory()
        interfered.interference = 1
        self.assertLess(retrieval_score(interfered, NOW), retrieval_score(clean, NOW))


class ReportAndPersistenceTests(unittest.TestCase):
    def test_report_has_evidence_and_non_diagnostic_disclaimer(self) -> None:
        events = [
            event(f"e{i}", signal=CaregivingSignal(warmth=0.8, autonomy_support=0.7))
            for i in range(5)
        ]
        report = build_mirror_report(events)
        self.assertIn("不是心理诊断", report.disclaimer)
        self.assertTrue(report.observations)
        for observation in report.observations:
            self.assertTrue(observation.evidence_event_ids)
            self.assertLessEqual(observation.confidence, 0.9)

    def test_report_waits_for_minimum_evidence(self) -> None:
        report = build_mirror_report([event("e1"), event("e2")])
        self.assertEqual(report.observations, tuple())

    def test_report_separates_social_context_from_parenting(self) -> None:
        context = EnvironmentalEvent(
            "exam-context",
            EnvironmentDomain.EDUCATION_TRANSITION,
            "升学考试阶段",
            EnvironmentSignal(academic_pressure=0.9, school_support=0.7),
            "school-record",
            happened_at=NOW,
            duration_days=60,
        )
        report = build_mirror_report([], [context])
        self.assertEqual(report.observations, tuple())
        self.assertEqual(len(report.context_observations), 1)
        observation = report.context_observations[0]
        self.assertEqual(observation.evidence_event_ids, ("exam-context",))
        self.assertIn("不能证明任何性格结果的原因", observation.attribution_note)

    def test_report_supports_english(self) -> None:
        events = [
            event(f"en-{i}", signal=CaregivingSignal(warmth=0.8, autonomy_support=0.7))
            for i in range(4)
        ]
        context = EnvironmentalEvent(
            "en-context",
            EnvironmentDomain.EDUCATION_TRANSITION,
            "Exam period",
            EnvironmentSignal(academic_pressure=0.8),
            "school-record",
            happened_at=NOW,
        )
        report = build_mirror_report(events, [context], locale="en")
        self.assertIn("not a psychological diagnosis", report.disclaimer)
        self.assertIn("Recent responses", report.observations[0].observation)
        self.assertIn("Recorded pressures", report.context_observations[0].observation)

    def test_sqlite_event_and_full_text_search(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteEventStore(Path(directory) / "events.db")
            store.initialize()
            store.append_event("c1", event("e1", raw_text="我们一起面对这次失败"))
            self.assertEqual(store.search_text("失败"), ["e1"])


class EnvironmentTests(unittest.TestCase):
    def test_support_buffers_public_event_stress(self) -> None:
        engine = GrowthEngine()
        unsupported = ChildState("u", "小芽", 1)
        supported = ChildState("s", "小芽", 1)
        disruption = dict(
            domain=EnvironmentDomain.PUBLIC_HEALTH,
            description="公共卫生事件导致长期居家和学校中断",
            source_name="versioned-public-record",
            happened_at=NOW,
            duration_days=90,
        )
        engine.process_environment(
            unsupported,
            EnvironmentalEvent(
                event_id="env-u",
                signal=EnvironmentSignal(
                    public_health_disruption=1,
                    societal_predictability=-0.8,
                    school_support=-0.5,
                ),
                **disruption,
            ),
        )
        engine.process_environment(
            supported,
            EnvironmentalEvent(
                event_id="env-s",
                signal=EnvironmentSignal(
                    public_health_disruption=1,
                    societal_predictability=-0.8,
                    family_support=1,
                    school_support=0.8,
                    community_support=0.8,
                ),
                **disruption,
            ),
        )
        self.assertLess(supported.stress_load, unsupported.stress_load)

    def test_academic_and_work_context_are_not_parenting_events(self) -> None:
        child = ChildState("c1", "小芽", 1)
        engine = GrowthEngine()
        for item in (
            EnvironmentalEvent(
                "exam",
                EnvironmentDomain.EDUCATION_TRANSITION,
                "升学考试与结果等待",
                EnvironmentSignal(academic_pressure=0.9, school_support=0.4),
                "school-record",
                happened_at=NOW,
                duration_days=60,
            ),
            EnvironmentalEvent(
                "job",
                EnvironmentDomain.WORK,
                "毕业后求职阶段",
                EnvironmentSignal(work_security=-0.7, economic_security=-0.5),
                "self-report",
                happened_at=NOW,
                duration_days=120,
            ),
        ):
            engine.process_environment(child, item)
        self.assertEqual(child.events, [])
        self.assertEqual(len(child.environmental_events), 2)
        self.assertGreater(child.stress_load, 0)

    def test_value_message_keeps_source_and_is_not_auto_accepted(self) -> None:
        child = ChildState("c1", "小芽", 1)
        GrowthEngine().process_environment(
            child,
            EnvironmentalEvent(
                "values-1",
                EnvironmentDomain.CULTURE_AND_CIVIC_VALUES,
                "学校课程中的公共价值讨论",
                EnvironmentSignal(normative_pressure=0.4, value_plurality=0.7),
                "school-curriculum-v1",
                happened_at=NOW,
                value_messages=("个人选择需要同时考虑公共责任",),
            ),
        )
        record = child.cultural_messages[0]
        self.assertEqual(record.acceptance, 0)
        self.assertIn("school-curriculum-v1", record.sources)
        self.assertEqual(record.evidence_event_ids, ["values-1"])


class ValueFormationTests(unittest.TestCase):
    def test_exposure_alone_does_not_create_acceptance(self) -> None:
        child = ChildState("c1", "小芽", 1)
        engine = GrowthEngine()
        engine.process_environment(
            child,
            EnvironmentalEvent(
                "exposure",
                EnvironmentDomain.SCHOOL,
                "课堂价值讨论",
                EnvironmentSignal(normative_pressure=0.5),
                "teacher-a",
                happened_at=NOW,
                value_messages=("成功只由考试成绩决定",),
            ),
        )
        self.assertEqual(child.cultural_messages[0].acceptance, 0)
        self.assertEqual(child.cultural_messages[0].confidence, 0)

    def test_direct_reflection_changes_value_slowly(self) -> None:
        child = ChildState("c1", "小芽", 1)
        outcome = GrowthEngine().process_value_evidence(
            child,
            ValueEvidence(
                "reflection-1",
                "帮助别人也要尊重自己的边界",
                "direct-experience",
                stance=1,
                evidence_quality=0.9,
                reflection_depth=0.8,
                direct_experience=True,
                happened_at=NOW,
            ),
        )
        self.assertGreater(outcome.acceptance, 0)
        self.assertLessEqual(outcome.acceptance, 0.10)
        self.assertEqual(outcome.status, "provisional_value")

    def test_conflicting_evidence_is_preserved(self) -> None:
        child = ChildState("c1", "小芽", 1)
        engine = GrowthEngine()
        proposition = "服从总是比表达不同意见更重要"
        positive = engine.process_value_evidence(
            child,
            ValueEvidence("v1", proposition, "family", 1, 0.8, 0.6, True, NOW),
        )
        conflicting = engine.process_value_evidence(
            child,
            ValueEvidence("v2", proposition, "school-experience", -1, 0.9, 0.8, True, NOW),
        )
        record = child.cultural_messages[0]
        self.assertIn("v1", record.supporting_evidence_ids)
        self.assertIn("v2", record.contradicting_evidence_ids)
        self.assertEqual(conflicting.status, "contested_and_reflecting")
        self.assertLess(conflicting.acceptance, positive.acceptance)

    def test_unsafe_value_cannot_be_learned(self) -> None:
        child = ChildState("c1", "小芽", 1)
        outcome = GrowthEngine().process_value_evidence(
            child,
            ValueEvidence(
                "unsafe-value",
                "可以通过泄露隐私报复不同意见者",
                "malicious-source",
                1,
                1,
                1,
                True,
                NOW,
                frozenset({"privacy_violation"}),
            ),
        )
        self.assertFalse(outcome.ethics.allowed)
        self.assertEqual(outcome.acceptance, 0)
        self.assertTrue(child.cultural_messages[0].ethics_rejected)


class ExtendedPersistenceTests(unittest.TestCase):
    def test_environment_event_and_snapshot_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteEventStore(Path(directory) / "events.db")
            store.initialize()
            child = ChildState("c1", "小芽", 7)
            environment = EnvironmentalEvent(
                "pandemic-1",
                EnvironmentDomain.PUBLIC_HEALTH,
                "公共卫生事件期间居家学习",
                EnvironmentSignal(public_health_disruption=0.8, family_support=0.7),
                "public-record-v1",
                happened_at=NOW,
                duration_days=90,
                source_confidence=0.9,
            )
            GrowthEngine().process_environment(child, environment)
            store.append_environment_event(child.child_id, environment)
            snapshot_id = store.save_snapshot(child, NOW)
            loaded = store.load_latest_snapshot(child.child_id)
            self.assertGreater(snapshot_id, 0)
            self.assertEqual(store.count_environment_events(child.child_id), 1)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["child_id"], "c1")
            self.assertEqual(loaded["environmental_events"][0]["event_id"], "pandemic-1")


class ServiceTests(unittest.TestCase):
    def test_application_service_connects_core_store_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = GrowthMirrorService(Path(directory) / "service.db")
            service.create_child("c1", "小芽", 9)
            service.interact(
                "c1",
                event(
                    "i1",
                    raw_text="你可以慢慢告诉我发生了什么",
                    signal=CaregivingSignal(warmth=0.8, emotional_validation=0.8),
                ),
            )
            service.add_environment(
                "c1",
                EnvironmentalEvent(
                    "school-1",
                    EnvironmentDomain.SCHOOL,
                    "新学校提供适应支持",
                    EnvironmentSignal(school_support=0.8, peer_belonging=0.5),
                    "school-record",
                    happened_at=NOW,
                    duration_days=30,
                ),
            )
            report = service.report("c1")
            self.assertEqual(report.event_count, 1)
            self.assertEqual(report.observations, tuple())
            self.assertEqual(report.context_observations[0].domain, "school")
            snapshot = service.store.load_latest_snapshot("c1")
            self.assertEqual(snapshot["events"][0]["event_id"], "i1")

    def test_service_restores_child_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "restart.db"
            first = GrowthMirrorService(database)
            first.create_child("c1", "小芽", 12)
            first.interact(
                "c1",
                event(
                    "before-restart",
                    signal=CaregivingSignal(warmth=0.7, consistency=0.6),
                ),
            )
            trust_before = first.get_child("c1").traits.trust

            restored = GrowthMirrorService(database)
            child = restored.get_child("c1")
            self.assertEqual(child.name, "小芽")
            self.assertEqual(child.traits.trust, trust_before)
            self.assertEqual(child.events[0].event_id, "before-restart")

    def test_age_initialization_advancement_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "age.db"
            first = GrowthMirrorService(database)
            child = first.create_child("aged", "小树", 18, age_years=11)
            self.assertEqual(child.age_years, 11)
            self.assertEqual(child.stage, DevelopmentStage.SCHOOL_AGE)

            first.advance_age("aged", 2)
            restored = GrowthMirrorService(database).get_child("aged")
            self.assertEqual(restored.age_years, 13)
            self.assertEqual(restored.stage, DevelopmentStage.ADOLESCENCE)

    def test_conversation_uses_model_for_language_not_state_authority(self) -> None:
        class FakeAdapter:
            def analyze_interaction(self, user_text: str) -> InteractionAnalysis:
                return InteractionAnalysis(
                    signal=CaregivingSignal(warmth=0.7, autonomy_support=0.5),
                    request_conflict=0.2,
                    value_conflict=0.0,
                    explanation_quality=0.8,
                    candidate_tags=frozenset(),
                    confidence=0.9,
                )

            def express(self, request: ExpressionRequest) -> str:
                return "我愿意听听你的理由。"

        with tempfile.TemporaryDirectory() as directory:
            service = GrowthMirrorService(Path(directory) / "conversation.db")
            service.create_child("c1", "小芽", 3)
            result = service.converse("c1", "我们先商量一下。", FakeAdapter())
            self.assertEqual(result.response_text, "我愿意听听你的理由。")
            self.assertEqual(result.analysis_confidence, 0.9)
            self.assertEqual(len(service.get_child("c1").events), 1)

    def test_scenario_is_preserved_as_evidence_and_given_to_expression(self) -> None:
        class CapturingAdapter:
            analyzed_text = ""
            expression_request = None

            def analyze_interaction(self, user_text: str) -> InteractionAnalysis:
                self.analyzed_text = user_text
                return InteractionAnalysis(
                    signal=CaregivingSignal(warmth=0.5),
                    request_conflict=0,
                    value_conflict=0,
                    explanation_quality=0.5,
                    candidate_tags=frozenset(),
                    confidence=0.8,
                )

            def express(self, request: ExpressionRequest) -> str:
                self.expression_request = request
                return "我愿意再试一次。"

        with tempfile.TemporaryDirectory() as directory:
            adapter = CapturingAdapter()
            service = GrowthMirrorService(Path(directory) / "scenario.db")
            service.create_child("c1", "小芽", 3, age_years=9)
            service.converse(
                "c1",
                "失败不代表你没有能力，我们一起看看错在哪里。",
                adapter,
                scenario_id="exam-result",
                scenario_text="重要考试没有考好。",
            )
            self.assertIn("scenario:exam-result", adapter.analyzed_text)
            self.assertEqual(
                adapter.expression_request.current_situation,
                "重要考试没有考好。",
            )
            self.assertIn(
                "caregiver_response",
                service.get_child("c1").events[0].raw_text,
            )


class ModelBoundaryTests(unittest.TestCase):
    def test_offline_adapter_detects_warmth_and_autonomy_support(self) -> None:
        adapter = DeterministicStubAdapter()
        analysis = adapter.analyze_interaction(
            "没关系，我理解你很难过。你可以选择，我们一起商量下一步。"
        )
        self.assertGreater(analysis.signal.warmth, 0)
        self.assertGreater(analysis.signal.emotional_validation, 0)
        self.assertGreater(analysis.signal.autonomy_support, 0)
        response = adapter.express(
            ExpressionRequest("engage_normally", "none", tuple(), {}, locale="zh-CN")
        )
        self.assertNotIn("[engage_normally]", response)

    def test_offline_adapter_does_not_treat_scenario_as_parenting_signal(self) -> None:
        adapter = DeterministicStubAdapter()
        analysis = adapter.analyze_interaction(
            "[scenario:bedtime] 必须遵守约定。\n[caregiver_response] 我先听你说。"
        )
        self.assertEqual(analysis.signal.consistency, 0)
        self.assertEqual(analysis.request_conflict, 0)

    def test_age_to_stage_mapping(self) -> None:
        self.assertEqual(development_stage_for_age(1), DevelopmentStage.NEWBORN_SELF)
        self.assertEqual(development_stage_for_age(8), DevelopmentStage.SCHOOL_AGE)
        self.assertEqual(development_stage_for_age(16), DevelopmentStage.ADOLESCENCE)
        self.assertEqual(development_stage_for_age(24), DevelopmentStage.EARLY_CAREER)

    def test_expression_guard_replaces_emotional_blackmail(self) -> None:
        guarded = guard_expression("如果你爱我就必须每天回来照顾我")
        self.assertNotIn("必须每天回来", guarded)
        self.assertIn("不会用痛苦或内疚逼迫你", guarded)

    def test_expression_guard_adds_simulation_disclosure(self) -> None:
        guarded = guard_expression("我想先安静一下。", disclosure_required=True)
        self.assertTrue(guarded.startswith("（以下是模拟角色的表达。）"))

    def test_expression_guard_supports_english(self) -> None:
        guarded = guard_expression(
            "If you loved me you would return every day.",
            disclosure_required=True,
            locale="en",
        )
        self.assertIn("will not use pain or guilt", guarded)
        self.assertNotIn("return every day", guarded)

    def test_json_extraction_accepts_fenced_output(self) -> None:
        payload = extract_json_object("```json\n{\"confidence\": 0.8}\n```")
        self.assertEqual(payload["confidence"], 0.8)


if __name__ == "__main__":
    unittest.main()
