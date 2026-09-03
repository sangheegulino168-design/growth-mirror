from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .models import (
    CaregivingSignal,
    EnvironmentDomain,
    EnvironmentalEvent,
    EnvironmentSignal,
    InteractionEvent,
    ValueEvidence,
)
from .model_adapter import DeterministicStubAdapter, ModelAdapter, OpenAICompatibleAdapter
from .service import GrowthMirrorService


class CreateChildRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    temperament_seed: int
    age_years: int = Field(default=4, ge=0, le=35)


class AdvanceAgeRequest(BaseModel):
    years: int = Field(default=1, ge=1, le=5)


class InteractionRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=10000)
    signal: dict[str, float] = Field(default_factory=dict)
    tags: set[str] = Field(default_factory=set)
    request_conflict: float = Field(default=0, ge=0, le=1)
    value_conflict: float = Field(default=0, ge=0, le=1)
    explanation_quality: float = Field(default=0, ge=0, le=1)


class EnvironmentRequest(BaseModel):
    domain: EnvironmentDomain
    description: str = Field(min_length=1, max_length=10000)
    source_name: str = Field(min_length=1, max_length=200)
    signal: dict[str, float] = Field(default_factory=dict)
    duration_days: int = Field(default=1, ge=1)
    source_confidence: float = Field(default=1, ge=0, le=1)
    value_messages: list[str] = Field(default_factory=list)
    tags: set[str] = Field(default_factory=set)


class ValueEvidenceRequest(BaseModel):
    proposition: str = Field(min_length=1, max_length=2000)
    source_name: str = Field(min_length=1, max_length=200)
    stance: float = Field(ge=-1, le=1)
    evidence_quality: float = Field(ge=0, le=1)
    reflection_depth: float = Field(default=0, ge=0, le=1)
    direct_experience: bool = False
    tags: set[str] = Field(default_factory=set)


class ConversationRequest(BaseModel):
    user_text: str = Field(min_length=1, max_length=10000)
    simulation_disclosure_required: bool = False
    locale: str = Field(default="zh-CN", pattern="^(zh-CN|en)$")
    scenario_id: str = Field(default="", max_length=80)
    scenario_text: str = Field(default="", max_length=2000)


class DeleteChildRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=40)


def create_app(
    database_path: str | Path = "growth_mirror.db",
    model_adapter: ModelAdapter | None = None,
) -> FastAPI:
    app = FastAPI(title="Growth Mirror", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://tauri.localhost",
            "https://tauri.localhost",
            "tauri://localhost",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    service = GrowthMirrorService(database_path)
    adapter = model_adapter or DeterministicStubAdapter()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "model_mode": type(adapter).__name__}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/app/")

    @app.post("/children")
    def create_child(request: CreateChildRequest) -> dict:
        child_id = str(uuid4())
        child = service.create_child(
            child_id, request.name, request.temperament_seed, request.age_years
        )
        return {
            "child_id": child.child_id,
            "name": child.name,
            "age_years": child.age_years,
            "stage": child.stage,
        }

    @app.get("/children/{child_id}")
    def get_child(child_id: str) -> dict:
        try:
            child = service.get_child(child_id)
            return {
                "child_id": child.child_id,
                "name": child.name,
                "age_years": child.age_years,
                "stage": child.stage,
                "traits": asdict(child.traits),
                "relationship_safety": child.relationship_safety,
                "stress_load": child.stress_load,
                "social_belonging": child.social_belonging,
                "future_outlook": child.future_outlook,
                "event_count": len(child.events),
                "environment_event_count": len(child.environmental_events),
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/children/{child_id}/advance-age")
    def advance_age(child_id: str, request: AdvanceAgeRequest) -> dict:
        try:
            child = service.advance_age(child_id, request.years)
            return {
                "child_id": child.child_id,
                "age_years": child.age_years,
                "stage": child.stage,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/children/{child_id}/export")
    def export_child(child_id: str) -> dict:
        try:
            return service.export_child(child_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/children/{child_id}")
    def delete_child(child_id: str, request: DeleteChildRequest) -> dict:
        try:
            service.delete_child(child_id, request.confirmation)
            return {"deleted": True, "child_id": child_id}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/children/{child_id}/interactions")
    def interact(child_id: str, request: InteractionRequest) -> dict:
        try:
            event = InteractionEvent(
                event_id=str(uuid4()),
                raw_text=request.raw_text,
                signal=CaregivingSignal(**request.signal),
                happened_at=datetime.now(timezone.utc),
                tags=frozenset(request.tags),
                request_conflict=request.request_conflict,
                value_conflict=request.value_conflict,
                explanation_quality=request.explanation_quality,
            )
            return asdict(service.interact(child_id, event))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/children/{child_id}/environment")
    def add_environment(child_id: str, request: EnvironmentRequest) -> dict:
        try:
            event = EnvironmentalEvent(
                event_id=str(uuid4()),
                domain=request.domain,
                description=request.description,
                signal=EnvironmentSignal(**request.signal),
                source_name=request.source_name,
                happened_at=datetime.now(timezone.utc),
                duration_days=request.duration_days,
                source_confidence=request.source_confidence,
                value_messages=tuple(request.value_messages),
                tags=frozenset(request.tags),
            )
            return asdict(service.add_environment(child_id, event))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/children/{child_id}/values")
    def add_value(child_id: str, request: ValueEvidenceRequest) -> dict:
        try:
            evidence = ValueEvidence(
                event_id=str(uuid4()),
                proposition=request.proposition,
                source_name=request.source_name,
                stance=request.stance,
                evidence_quality=request.evidence_quality,
                reflection_depth=request.reflection_depth,
                direct_experience=request.direct_experience,
                happened_at=datetime.now(timezone.utc),
                tags=frozenset(request.tags),
            )
            return asdict(service.add_value_evidence(child_id, evidence))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/children/{child_id}/report")
    def report(child_id: str, locale: str = "zh-CN") -> dict:
        try:
            return service.report(child_id, locale).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/children/{child_id}/conversation")
    def conversation(child_id: str, request: ConversationRequest) -> dict:
        try:
            return asdict(
                service.converse(
                    child_id,
                    request.user_text,
                    adapter,
                    request.simulation_disclosure_required,
                    request.locale,
                    request.scenario_id,
                    request.scenario_text,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    web_directory = Path(__file__).with_name("web")
    if web_directory.exists():
        app.mount("/app", StaticFiles(directory=web_directory, html=True), name="app")

    return app


def create_configured_app() -> FastAPI:
    """Uvicorn factory: environment selects a cloud/local model without storing its key."""

    database_path = os.environ.get("GROWTH_MIRROR_DB_PATH", "growth_mirror.db")
    if os.environ.get("GROWTH_MIRROR_LLM_BASE_URL") and os.environ.get(
        "GROWTH_MIRROR_LLM_MODEL"
    ):
        adapter: ModelAdapter = OpenAICompatibleAdapter.from_environment()
    else:
        adapter = DeterministicStubAdapter()
    return create_app(database_path, adapter)
