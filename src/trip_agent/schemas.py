"""Runtime contracts: uncertainty and evidence are part of the output."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(StrictModel):
    value: str | None = None
    status: Literal["unknown", "user_stated", "inferred", "proposed", "conflicting"] = "unknown"
    source_artifact_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def evidence(self):
        if self.status == "user_stated" and (not self.value or not self.source_artifact_ids):
            raise ValueError("User-stated facts require a value and source request artifact IDs")
        if self.status == "unknown" and self.value is not None:
            raise ValueError("Unknown facts must have a null value")
        return self


class TripState(StrictModel):
    origin: Fact = Field(default_factory=Fact)
    destination: Fact = Field(default_factory=Fact)
    dates: Fact = Field(default_factory=Fact)
    duration: Fact = Field(default_factory=Fact)
    travelers: Fact = Field(default_factory=Fact)
    budget: Fact = Field(default_factory=Fact)
    preferences: list[Fact] = Field(default_factory=list)
    exclusions: list[Fact] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class Suggestion(StrictModel):
    destination_id: str
    reasoning: str
    accommodation_id: str | None = None
    budget_artifact_id: str | None = None
    rough_budget: str = Field(description="Explain the tool-calculated budget, or why it cannot yet be estimated")
    evidence_artifact_ids: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class TripResponse(StrictModel):
    status: Literal["suggestions", "needs_clarification", "no_match"]
    message: str
    trip_state: TripState
    questions: list[str] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "needs_clarification" and not self.questions:
            raise ValueError("Clarification requires at least one question")
        if self.status == "suggestions" and not self.suggestions:
            raise ValueError("Suggestions status requires a suggestion")
        if self.status == "no_match" and self.suggestions:
            raise ValueError("No-match responses cannot include suggestions")
        return self
