"""Multiple-choice clarification cards (CONTRACTS A.7 / A.9).

Agent nodes never interrupt by themselves. They hand their open questions to
``queue_questions``, which either stores a pending card (the graph then
interrupts in ``clarify_gate``) or, once the round limit is spent, resolves
every question to its default/recommended option and records the assumption.
"""

from typing import Literal, TypedDict

from flask import current_app
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.api import AppError
from app.utils.ids import new_id

ASKERS = ("intake", "research", "director", "creative", "production")


class ClarifyState(TypedDict, total=False):
    """Keys the helpers below read and write. A graph's state schema must
    include them (e.g. ``class AgentStateV2(ClarifyState, total=False)``),
    otherwise LangGraph drops the updates."""

    status: str
    pending_card: dict | None
    clarify_resume_status: str | None
    clarifications: list[dict]
    assumptions: list[str]
    clarify_rounds: int
    last_command_id: str | None


class Option(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    option_id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    detail: str | None = Field(default=None, max_length=300)
    image_artifact_id: str | None = Field(default=None, min_length=1, max_length=80)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=200)
    why: str = Field(min_length=1, max_length=300)
    options: list[Option] = Field(min_length=2, max_length=4)
    recommended_option_id: str | None = None
    allow_free_text: bool = False
    blocking: bool = True
    default_option_id: str | None = None

    @model_validator(mode="after")
    def _consistent_options(self):
        ids = [option.option_id for option in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Duplicate option_id in question {self.question_id}")
        for field in ("recommended_option_id", "default_option_id"):
            value = getattr(self, field)
            if value is not None and value not in ids:
                raise ValueError(f"{field} {value!r} is not an option of question {self.question_id}")
        if not self.blocking and self.default_option_id is None:
            raise ValueError(f"Non-blocking question {self.question_id} needs default_option_id")
        return self

    def option(self, option_id: str) -> Option | None:
        return next((item for item in self.options if item.option_id == option_id), None)


class ClarificationCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(min_length=1, max_length=80)
    asked_by: Literal["intake", "research", "director", "creative", "production"]
    questions: list[Question] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def _unique_questions(self):
        ids = [question.question_id for question in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate question_id in card")
        return self


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_id: str = Field(min_length=1, max_length=40)
    option_id: str | None = Field(default=None, min_length=1, max_length=40)
    text: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _one_choice(self):
        if (self.option_id is None) == (self.text is None):
            raise ValueError("Give exactly one of option_id or text")
        return self


class AnswerSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(min_length=1, max_length=80)
    answers: list[Answer] = Field(default_factory=list, max_length=3)
    use_defaults: bool = False


def max_rounds() -> int:
    return int(current_app.config.get("AGENT_MAX_CLARIFY_ROUNDS", 2))


def build_card(asked_by: str, questions: list[dict | Question]) -> ClarificationCard:
    """Validate agent-produced questions into a card with a fresh card_id."""
    try:
        return ClarificationCard.model_validate(
            {"card_id": new_id("card"), "asked_by": asked_by, "questions": questions}
        )
    except ValidationError as error:
        raise AppError(
            "INVALID_CLARIFICATION",
            f"{asked_by} produced an invalid clarification card",
            422,
            payload={"errors": error.errors(include_url=False, include_context=False)},
        ) from error


def _resolution(question: Question, option: Option | None, source: str, text: str | None = None) -> dict:
    return {
        "question_id": question.question_id,
        "question": question.text,
        "option_id": option.option_id if option else None,
        "label": option.label if option else None,
        "text": text,
        "source": source,
    }


def _fallback(question: Question) -> dict:
    option_id = question.default_option_id or question.recommended_option_id
    source = "default" if question.default_option_id else "recommended" if option_id else "fallback"
    return _resolution(question, question.option(option_id) if option_id else question.options[0], source)


def resolve_answers(card: ClarificationCard | dict, submission: AnswerSubmission | dict) -> dict[str, dict]:
    """Turn a submission into one resolution per question, or raise.

    Unanswered non-blocking questions take their default (use_defaults only
    makes that explicit); unanswered blocking questions are an error.
    """
    card = ClarificationCard.model_validate(card)
    submission = AnswerSubmission.model_validate(submission)
    if submission.card_id != card.card_id:
        raise AppError("INVALID_ANSWER", "Answers belong to a different clarification card", 422)
    questions = {question.question_id: question for question in card.questions}
    resolved: dict[str, dict] = {}
    for answer in submission.answers:
        question = questions.get(answer.question_id)
        if question is None:
            raise AppError("INVALID_ANSWER", f"Unknown question {answer.question_id}", 422)
        if answer.question_id in resolved:
            raise AppError("INVALID_ANSWER", f"Question {answer.question_id} answered twice", 422)
        if answer.option_id is not None:
            option = question.option(answer.option_id)
            if option is None:
                raise AppError("INVALID_ANSWER", f"Unknown option {answer.option_id} for {answer.question_id}", 422)
            resolved[answer.question_id] = _resolution(question, option, "user")
        else:
            if not question.allow_free_text:
                raise AppError("INVALID_ANSWER", f"Question {answer.question_id} does not accept free text", 422)
            resolved[answer.question_id] = _resolution(question, None, "user", answer.text)
    missing = [qid for qid, question in questions.items() if qid not in resolved and question.blocking]
    if missing:
        raise AppError(
            "CLARIFICATION_INCOMPLETE",
            "Every blocking question needs an answer",
            409,
            payload={"missing": missing},
        )
    for qid, question in questions.items():
        if qid not in resolved:
            resolved[qid] = _resolution(question, question.option(question.default_option_id), "default")
    return resolved


SOURCE_LABELS = {"default": "默认", "recommended": "推荐", "fallback": "首个"}


def _assumption(resolution: dict) -> str:
    choice = resolution["label"] or resolution["text"]
    return f"{resolution['question']} → {choice}（未询问，按{SOURCE_LABELS[resolution['source']]}选项）"


def queue_questions(state: dict, asked_by: str, questions: list, resume_status: str) -> dict:
    """State update for a node that wants to ask the user.

    Returns ``{}`` when there is nothing to ask. Within the round limit it sets
    ``pending_card`` and status ``awaiting_input``; past the limit it resolves
    the questions automatically and records them as assumptions.
    """
    if not questions:
        return {}
    card = build_card(asked_by, questions)
    rounds = state.get("clarify_rounds", 0)
    if rounds < max_rounds():
        return {
            "pending_card": card.model_dump(mode="json"),
            "clarify_resume_status": resume_status,
            "status": "awaiting_input",
        }
    resolutions = {question.question_id: _fallback(question) for question in card.questions}
    return {
        "clarifications": [
            *state.get("clarifications", []),
            {"card": card.model_dump(mode="json"), "answers": resolutions, "asked": False},
        ],
        "assumptions": [*state.get("assumptions", []), *(_assumption(item) for item in resolutions.values())],
    }


def clarify_gate(state: dict) -> dict:
    """Graph node: interrupt for the pending card, then record the answers."""
    card = state.get("pending_card")
    if not card:
        return {}
    decision = interrupt({"kind": "clarify", "card": card})
    resolutions = resolve_answers(card, {
        "card_id": decision.get("card_id"),
        "answers": decision.get("answers", []),
        "use_defaults": decision.get("use_defaults", False),
    })
    return {
        "pending_card": None,
        "clarifications": [
            *state.get("clarifications", []),
            {"card": card, "answers": resolutions, "asked": True},
        ],
        "clarify_rounds": state.get("clarify_rounds", 0) + 1,
        "status": state.get("clarify_resume_status") or "understanding",
        "clarify_resume_status": None,
        "last_command_id": decision.get("command_id"),
    }


def answer_for(state: dict, question_id: str, asked_by: str | None = None) -> dict | None:
    """Latest resolution for a question id (optionally from one asker)."""
    for record in reversed(state.get("clarifications", [])):
        if asked_by and record["card"]["asked_by"] != asked_by:
            continue
        if question_id in record["answers"]:
            return record["answers"][question_id]
    return None
