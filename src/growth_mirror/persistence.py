from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .models import (
    CaregivingSignal,
    ChildState,
    CulturalMessageRecord,
    DevelopmentStage,
    EnvironmentalEvent,
    EnvironmentDomain,
    EnvironmentSignal,
    InteractionEvent,
    MemoryRecord,
    TraitState,
    development_stage_for_age,
)


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA secure_delete = ON;

CREATE TABLE IF NOT EXISTS interaction_event (
    event_id TEXT PRIMARY KEY,
    child_id TEXT NOT NULL,
    happened_at TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    signal_json TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    request_conflict REAL NOT NULL,
    value_conflict REAL NOT NULL,
    explanation_quality REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS interaction_event_fts USING fts5(
    event_id UNINDEXED,
    raw_text,
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS state_snapshot (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    state_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS safety_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    child_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS environmental_event (
    event_id TEXT PRIMARY KEY,
    child_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    description TEXT NOT NULL,
    source_name TEXT NOT NULL,
    happened_at TEXT NOT NULL,
    duration_days INTEGER NOT NULL,
    source_confidence REAL NOT NULL,
    signal_json TEXT NOT NULL,
    value_messages_json TEXT NOT NULL,
    tags_json TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS environmental_event_fts USING fts5(
    event_id UNINDEXED,
    description,
    tokenize='trigram'
);
"""


class SQLiteEventStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            audit_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(safety_audit)")
            }
            if "child_id" not in audit_columns:
                connection.execute(
                    "ALTER TABLE safety_audit ADD COLUMN child_id TEXT NOT NULL DEFAULT ''"
                )

    def append_event(self, child_id: str, event: InteractionEvent) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO interaction_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    child_id,
                    event.happened_at.isoformat(),
                    event.raw_text,
                    json.dumps(asdict(event.signal), ensure_ascii=False),
                    json.dumps(sorted(event.tags), ensure_ascii=False),
                    event.request_conflict,
                    event.value_conflict,
                    event.explanation_quality,
                ),
            )
            connection.execute(
                "INSERT INTO interaction_event_fts(event_id, raw_text) VALUES (?, ?)",
                (event.event_id, event.raw_text),
            )

    def append_environment_event(self, child_id: str, event: EnvironmentalEvent) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO environmental_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    child_id,
                    event.domain.value,
                    event.description,
                    event.source_name,
                    event.happened_at.isoformat(),
                    event.duration_days,
                    event.source_confidence,
                    json.dumps(asdict(event.signal), ensure_ascii=False),
                    json.dumps(event.value_messages, ensure_ascii=False),
                    json.dumps(sorted(event.tags), ensure_ascii=False),
                ),
            )
            connection.execute(
                "INSERT INTO environmental_event_fts(event_id, description) VALUES (?, ?)",
                (event.event_id, event.description),
            )

    def append_safety_audit(
        self,
        child_id: str,
        event_id: str,
        allowed: bool,
        reason: str,
        created_at: datetime | None = None,
    ) -> None:
        timestamp = created_at or datetime.now(timezone.utc)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO safety_audit(event_id, allowed, reason, created_at, child_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, int(allowed), reason, timestamp.isoformat(), child_id),
            )

    def list_safety_audits(self, child_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, allowed, reason, created_at
                FROM safety_audit
                WHERE child_id = ?
                   OR event_id IN (
                       SELECT event_id FROM interaction_event WHERE child_id = ?
                   )
                   OR event_id IN (
                       SELECT event_id FROM environmental_event WHERE child_id = ?
                   )
                ORDER BY audit_id
                """,
                (child_id, child_id, child_id),
            ).fetchall()
        return [
            {
                "event_id": str(row["event_id"]),
                "allowed": bool(row["allowed"]),
                "reason": str(row["reason"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def delete_child(self, child_id: str) -> None:
        """Securely remove a child's events, indexes, audits, and snapshots."""

        with self.connect() as connection:
            connection.execute("PRAGMA secure_delete = ON")
            interaction_ids = [
                str(row["event_id"])
                for row in connection.execute(
                    "SELECT event_id FROM interaction_event WHERE child_id = ?",
                    (child_id,),
                )
            ]
            environment_ids = [
                str(row["event_id"])
                for row in connection.execute(
                    "SELECT event_id FROM environmental_event WHERE child_id = ?",
                    (child_id,),
                )
            ]
            event_ids = interaction_ids + environment_ids

            if interaction_ids:
                placeholders = ",".join("?" for _ in interaction_ids)
                connection.execute(
                    f"DELETE FROM interaction_event_fts WHERE event_id IN ({placeholders})",
                    interaction_ids,
                )
            if environment_ids:
                placeholders = ",".join("?" for _ in environment_ids)
                connection.execute(
                    f"DELETE FROM environmental_event_fts WHERE event_id IN ({placeholders})",
                    environment_ids,
                )
            if event_ids:
                placeholders = ",".join("?" for _ in event_ids)
                connection.execute(
                    f"DELETE FROM safety_audit WHERE child_id = ? OR event_id IN ({placeholders})",
                    [child_id, *event_ids],
                )
            else:
                connection.execute(
                    "DELETE FROM safety_audit WHERE child_id = ?", (child_id,)
                )
            connection.execute(
                "DELETE FROM interaction_event WHERE child_id = ?", (child_id,)
            )
            connection.execute(
                "DELETE FROM environmental_event WHERE child_id = ?", (child_id,)
            )
            connection.execute(
                "DELETE FROM state_snapshot WHERE child_id = ?", (child_id,)
            )
        # Rebuild the file so securely deleted free pages are not retained.
        with self.connect() as connection:
            connection.execute("VACUUM")

    def save_snapshot(self, state: ChildState, created_at: datetime | None = None) -> int:
        timestamp = created_at or datetime.now(timezone.utc)
        state_json = json.dumps(asdict(state), ensure_ascii=False, default=_json_default)
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO state_snapshot(child_id, created_at, state_json) VALUES (?, ?, ?)",
                (state.child_id, timestamp.isoformat(), state_json),
            )
            return int(cursor.lastrowid)

    def load_latest_snapshot(self, child_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT state_json FROM state_snapshot
                WHERE child_id = ? ORDER BY snapshot_id DESC LIMIT 1
                """,
                (child_id,),
            ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def restore_child(self, child_id: str) -> ChildState | None:
        payload = self.load_latest_snapshot(child_id)
        return child_from_snapshot(payload) if payload else None

    def list_child_ids(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT child_id FROM state_snapshot ORDER BY child_id"
            ).fetchall()
        return [str(row["child_id"]) for row in rows]

    def count_environment_events(self, child_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT count(*) AS total FROM environmental_event WHERE child_id = ?",
                (child_id,),
            ).fetchone()
        return int(row["total"])

    def search_text(self, query: str) -> list[str]:
        with self.connect() as connection:
            if len(query) >= 3:
                rows = connection.execute(
                    "SELECT event_id FROM interaction_event_fts WHERE raw_text MATCH ?",
                    (query,),
                ).fetchall()
            else:
                # FTS5 trigram cannot index one- or two-character CJK queries.
                rows = connection.execute(
                    "SELECT event_id FROM interaction_event WHERE instr(raw_text, ?) > 0",
                    (query,),
                ).fetchall()
        return [str(row["event_id"]) for row in rows]


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def child_to_payload(state: ChildState) -> dict:
    return json.loads(json.dumps(asdict(state), ensure_ascii=False, default=_json_default))


def child_from_snapshot(payload: dict) -> ChildState:
    events = [
        InteractionEvent(
            event_id=item["event_id"],
            raw_text=item["raw_text"],
            signal=CaregivingSignal(**item["signal"]),
            happened_at=datetime.fromisoformat(item["happened_at"]),
            tags=frozenset(item["tags"]),
            request_conflict=item["request_conflict"],
            value_conflict=item["value_conflict"],
            explanation_quality=item["explanation_quality"],
        )
        for item in payload["events"]
    ]
    environmental_events = [
        EnvironmentalEvent(
            event_id=item["event_id"],
            domain=EnvironmentDomain(item["domain"]),
            description=item["description"],
            signal=EnvironmentSignal(**item["signal"]),
            source_name=item["source_name"],
            happened_at=datetime.fromisoformat(item["happened_at"]),
            duration_days=item["duration_days"],
            source_confidence=item["source_confidence"],
            value_messages=tuple(item["value_messages"]),
            tags=frozenset(item["tags"]),
        )
        for item in payload["environmental_events"]
    ]
    memories = [
        MemoryRecord(
            **{
                **item,
                "created_at": datetime.fromisoformat(item["created_at"]),
                "last_recalled_at": datetime.fromisoformat(item["last_recalled_at"]),
            }
        )
        for item in payload["memories"]
    ]
    cultural_messages = [
        CulturalMessageRecord(
            proposition=item["proposition"],
            sources=set(item["sources"]),
            evidence_event_ids=list(item["evidence_event_ids"]),
            exposure_count=item["exposure_count"],
            acceptance=item["acceptance"],
            confidence=item["confidence"],
            supporting_evidence_ids=list(item["supporting_evidence_ids"]),
            contradicting_evidence_ids=list(item["contradicting_evidence_ids"]),
            reflection_count=item["reflection_count"],
            ethics_rejected=item["ethics_rejected"],
        )
        for item in payload["cultural_messages"]
    ]
    return ChildState(
        child_id=payload["child_id"],
        name=payload["name"],
        temperament_seed=payload["temperament_seed"],
        age_years=payload.get("age_years", 4),
        stage=(
            DevelopmentStage(payload["stage"])
            if "age_years" in payload
            else development_stage_for_age(4)
        ),
        traits=TraitState(**payload["traits"]),
        relationship_safety=payload["relationship_safety"],
        control_pressure=payload["control_pressure"],
        stress_load=payload["stress_load"],
        social_belonging=payload["social_belonging"],
        future_outlook=payload["future_outlook"],
        institutional_trust=payload["institutional_trust"],
        events=events,
        environmental_events=environmental_events,
        cultural_messages=cultural_messages,
        memories=memories,
    )
