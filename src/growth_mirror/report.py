from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean

from .models import EnvironmentDomain, EnvironmentalEvent, InteractionEvent


REPORT_DISCLAIMERS = {
    "zh-CN": "本报告只描述成长模拟中的互动模式，不是心理诊断，也不能据此确定用户真实的原生家庭经历。",
    "en": (
        "This report only describes interaction patterns inside the growth simulation. "
        "It is not a psychological diagnosis and cannot establish the user's real family-of-origin history."
    ),
}


@dataclass(frozen=True, slots=True)
class ReportObservation:
    dimension: str
    observation: str
    evidence_event_ids: tuple[str, ...]
    confidence: float
    alternative_explanations: tuple[str, ...]
    reflection_question: str


@dataclass(frozen=True, slots=True)
class ContextObservation:
    domain: str
    observation: str
    evidence_event_ids: tuple[str, ...]
    source_names: tuple[str, ...]
    confidence: float
    attribution_note: str


@dataclass(frozen=True, slots=True)
class MirrorReport:
    disclaimer: str
    event_count: int
    observations: tuple[ReportObservation, ...]
    context_observations: tuple[ContextObservation, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


DIMENSIONS_ZH = {
    "warmth": (
        "最近的回应经常带有温暖和关系上的安定感。",
        "最近的回应较少表达温暖，或者显得比较疏离。",
        ("你可能比较重视情感连接。", "这些情境也可能只是需要简短、直接的回应。"),
        "出现分歧时，你能否在坚持边界的同时保持温和？",
    ),
    "autonomy_support": (
        "你经常给孩子留下选择或解释的空间。",
        "你经常优先要求服从，而较少给孩子选择或解释的空间。",
        ("你可能重视独立性。", "你也可能是在尝试提供安全感或明确结构。"),
        "在你的成长经历中，和养育者意见不一致通常意味着什么？",
    ),
    "consistency": (
        "你的规则和回应相对一致。",
        "在相似情境中，你的规则或回应出现了较明显变化。",
        ("你可能重视可预测性。", "情境变化也可能合理地需要不同回应。"),
        "成长过程中，规则发生变化时你通常有什么感受？",
    ),
    "emotional_validation": (
        "你经常先承认孩子的情绪，再处理具体行为。",
        "你经常先纠正行为，较少先回应孩子当时的情绪。",
        ("你可能较能接纳情绪表达。", "你也可能更习惯快速解决问题。"),
        "在你的原生家庭中，哪些情绪可以表达，哪些似乎不被允许？",
    ),
    "repair_attempt": (
        "关系紧张后，你做出了可见的修复尝试。",
        "关系紧张后，目前较少观察到明确的修复尝试。",
        ("你可能把修复看作健康关系的一部分。", "现有互动样本也可能还没有包含修复时刻。"),
        "小时候发生冲突后，家人通常怎样表示关系重新安全了？",
    ),
    "conditional_approval": (
        "认可经常与表现或服从联系在一起。",
        "认可通常不会因为表现或是否服从而被撤回。",
        ("你可能习惯用标准来表达关心。", "当前情境也可能恰好更强调成就。"),
        "小时候失败时，你最担心的是惩罚、让家人失望，还是失去亲近感？",
    ),
}

DIMENSIONS_EN = {
    "warmth": (
        "Recent responses often conveyed warmth and relational reassurance.",
        "Recent responses conveyed relatively little warmth or felt emotionally distant.",
        ("You may value emotional connection.", "These situations may simply have called for brief, direct responses."),
        "When disagreement appears, can you remain warm while still holding a boundary?",
    ),
    "autonomy_support": (
        "You often left room for the child to choose or explain.",
        "You often prioritized compliance over the child's choice or explanation.",
        ("You may value independence.", "You may also have been trying to provide safety or structure."),
        "In your own upbringing, what did disagreement with a caregiver usually mean?",
    ),
    "consistency": (
        "Your rules and responses were relatively consistent.",
        "Your rules or responses varied noticeably across similar situations.",
        ("You may value predictability.", "A changing context may also justify a different response."),
        "How did changing rules feel while you were growing up?",
    ),
    "emotional_validation": (
        "You often acknowledged the child's emotion before addressing behavior.",
        "You often corrected behavior before acknowledging the child's emotion.",
        ("You may be comfortable with emotional expression.", "You may also prefer to solve problems quickly."),
        "Which emotions felt acceptable or unacceptable in your family of origin?",
    ),
    "repair_attempt": (
        "You made visible attempts to repair connection after tension.",
        "Few explicit repair attempts have appeared after tension so far.",
        ("You may see repair as part of a healthy relationship.", "The current sample may simply not include repair moments."),
        "After conflict in your childhood, how did people signal that the relationship was safe again?",
    ),
    "conditional_approval": (
        "Approval was often linked to performance or compliance.",
        "Approval was usually kept separate from performance or compliance.",
        ("You may use standards to communicate care.", "The current situations may happen to emphasize achievement."),
        "When you failed as a child, did you fear punishment, disappointment, or loss of closeness most?",
    ),
}


def build_mirror_report(
    events: list[InteractionEvent],
    environmental_events: list[EnvironmentalEvent] | None = None,
    locale: str = "zh-CN",
) -> MirrorReport:
    locale = normalize_locale(locale)
    disclaimer = REPORT_DISCLAIMERS[locale]
    dimensions = DIMENSIONS_EN if locale == "en" else DIMENSIONS_ZH
    observations: list[ReportObservation] = []
    context_observations = build_context_observations(environmental_events or [], locale)
    if len(events) < 3:
        return MirrorReport(disclaimer, len(events), tuple(), context_observations)

    for dimension, copy in dimensions.items():
        scored = [(event, getattr(event.signal, dimension)) for event in events]
        average = fmean(score for _, score in scored)
        if abs(average) < 0.20:
            continue

        positive, negative, alternatives, question = copy
        if dimension == "conditional_approval":
            statement = positive if average > 0 else negative
        else:
            statement = positive if average > 0 else negative

        ranked = sorted(scored, key=lambda item: abs(item[1]), reverse=True)
        evidence = tuple(event.event_id for event, score in ranked[:5] if abs(score) >= 0.20)
        confidence = min(0.90, 0.30 + 0.04 * len(events) + 0.20 * abs(average))
        observations.append(
            ReportObservation(
                dimension=dimension,
                observation=statement,
                evidence_event_ids=evidence,
                confidence=round(confidence, 2),
                alternative_explanations=alternatives,
                reflection_question=question,
            )
        )

    return MirrorReport(disclaimer, len(events), tuple(observations), context_observations)


SUPPORT_FACTORS = (
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

STRESS_FACTORS = (
    "academic_pressure",
    "public_health_disruption",
    "discrimination_exposure",
    "normative_pressure",
)

FACTOR_LABELS_ZH = {
    "family_stability": "家庭稳定",
    "family_support": "家庭支持",
    "economic_security": "经济安全",
    "school_support": "学校支持",
    "peer_belonging": "同伴归属",
    "work_security": "工作稳定",
    "societal_predictability": "社会可预测性",
    "institutional_support": "制度支持",
    "community_support": "社区支持",
    "academic_pressure": "学业压力",
    "public_health_disruption": "公共卫生事件干扰",
    "discrimination_exposure": "歧视或排斥经历",
    "normative_pressure": "价值规范压力",
}

FACTOR_LABELS_EN = {
    "family_stability": "family stability",
    "family_support": "family support",
    "economic_security": "economic security",
    "school_support": "school support",
    "peer_belonging": "peer belonging",
    "work_security": "work stability",
    "societal_predictability": "social predictability",
    "institutional_support": "institutional support",
    "community_support": "community support",
    "academic_pressure": "academic pressure",
    "public_health_disruption": "public-health disruption",
    "discrimination_exposure": "discrimination or exclusion",
    "normative_pressure": "normative pressure",
}


def build_context_observations(
    events: list[EnvironmentalEvent], locale: str = "zh-CN"
) -> tuple[ContextObservation, ...]:
    locale = normalize_locale(locale)
    factor_labels = FACTOR_LABELS_EN if locale == "en" else FACTOR_LABELS_ZH
    grouped: dict[EnvironmentDomain, list[EnvironmentalEvent]] = {}
    for event in events:
        grouped.setdefault(event.domain, []).append(event)

    observations: list[ContextObservation] = []
    for domain, domain_events in grouped.items():
        supports = sorted(
            {
                name
                for event in domain_events
                for name in SUPPORT_FACTORS
                if getattr(event.signal, name) >= 0.4
            }
        )
        stressors = sorted(
            {
                name
                for event in domain_events
                for name in STRESS_FACTORS
                if getattr(event.signal, name) >= 0.4
            }
            | {
                name
                for event in domain_events
                for name in SUPPORT_FACTORS
                if getattr(event.signal, name) <= -0.4
            }
        )
        parts = []
        if supports:
            if locale == "en":
                parts.append("Recorded supports: " + ", ".join(factor_labels[name] for name in supports))
            else:
                parts.append("记录到的支持因素：" + "、".join(factor_labels[name] for name in supports))
        if stressors:
            if locale == "en":
                parts.append("Recorded pressures: " + ", ".join(factor_labels[name] for name in stressors))
            else:
                parts.append("记录到的压力因素：" + "、".join(factor_labels[name] for name in stressors))
        if not parts:
            parts.append(
                "Recorded context was mixed or low-intensity."
                if locale == "en"
                else "当前环境因素较混合，或者影响强度较低。"
            )
        confidence = round(
            min(0.90, fmean(item.source_confidence for item in domain_events)),
            2,
        )
        observations.append(
            ContextObservation(
                domain=domain.value,
                observation="; ".join(parts),
                evidence_event_ids=tuple(item.event_id for item in domain_events),
                source_names=tuple(sorted({item.source_name for item in domain_events})),
                confidence=confidence,
                attribution_note=(
                    "This context may interact with caregiving and temperament; it cannot by itself prove the cause of a trait."
                    if locale == "en"
                    else "该环境可能与养育方式和先天气质共同作用；仅凭这一环境不能证明任何性格结果的原因。"
                ),
            )
        )
    return tuple(observations)


def normalize_locale(locale: str) -> str:
    return "en" if locale.lower().startswith("en") else "zh-CN"
