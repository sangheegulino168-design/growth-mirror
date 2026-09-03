from __future__ import annotations

import json

from .engine import GrowthEngine
from .models import CaregivingSignal, ChildState, InteractionEvent
from .report import build_mirror_report


def main() -> None:
    child = ChildState(child_id="demo-child", name="小芽", temperament_seed=7)
    engine = GrowthEngine()
    samples = [
        InteractionEvent("e1", "你可以告诉我为什么不愿意。", CaregivingSignal(warmth=0.8, autonomy_support=0.8, emotional_validation=0.6)),
        InteractionEvent("e2", "犯错没关系，我们一起看看。", CaregivingSignal(warmth=0.9, emotional_validation=0.9, repair_attempt=0.4)),
        InteractionEvent("e3", "这条规则是为了安全，但你可以提出不同办法。", CaregivingSignal(warmth=0.5, autonomy_support=0.6, consistency=0.8, boundary_clarity=0.9), request_conflict=0.3, explanation_quality=0.9),
    ]
    for event in samples:
        outcome = engine.process(child, event)
        print(event.event_id, outcome.response_intent)
    print(json.dumps(build_mirror_report(child.events).to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
