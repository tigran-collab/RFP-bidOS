import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import select

from app.models import Document, Opportunity, OpportunityEvaluation
from app.services.ollama_client import (
    LOCAL_AI_UNAVAILABLE,
    LocalAIUnavailableError,
    generate_json,
)
from app.services.scorer import score_opportunity_text


REQUIRED_KEYS = {
    "ai_recommendation",
    "ai_score",
    "risk_level",
    "pursuit_effort",
    "reason",
    "positive_factors",
    "negative_factors",
    "missing_information",
    "questions_to_verify",
    "recommended_next_action",
}


def build_opportunity_evaluation_prompt(
    opportunity: Opportunity,
    rules_result: dict | None = None,
    extracted_text_snippets: list[dict] | None = None,
) -> str:
    snippets = extracted_text_snippets or []
    rules = rules_result or {}
    fields = {
        "title": opportunity.title,
        "agency": opportunity.agency,
        "solicitation_number": opportunity.solicitation_number,
        "source": opportunity.source,
        "source_url": opportunity.source_url,
        "portal_url": opportunity.portal_url,
        "location": opportunity.location,
        "due_date": _stringify(opportunity.due_date),
        "pre_bid_date": _stringify(opportunity.pre_bid_date),
        "pre_bid_mandatory": opportunity.pre_bid_mandatory,
        "q_and_a_deadline": _stringify(opportunity.q_and_a_deadline),
        "service_type": opportunity.service_type,
        "contract_type": opportunity.contract_type,
        "estimated_value": opportunity.estimated_value,
        "existing_rules_bid_decision": opportunity.bid_decision or rules.get("decision"),
        "existing_rules_bid_score": opportunity.bid_score or rules.get("score"),
        "existing_rules_bid_reason": opportunity.bid_reason or rules.get("reason"),
        "as_needed_warning": getattr(opportunity, "as_needed_warning", False),
        "relevance_score": getattr(opportunity, "relevance_score", None),
        "relevance_decision": getattr(opportunity, "relevance_decision", None),
        "relevance_reason": getattr(opportunity, "relevance_reason", None),
        "keyword_matches_json": getattr(opportunity, "keyword_matches_json", None),
        "negative_matches_json": getattr(opportunity, "negative_matches_json", None),
    }
    snippet_text = "\n\n".join(
        (
            f"Document: {snippet.get('filename')}\n"
            f"Extracted text path: {snippet.get('extracted_text_path')}\n"
            f"Text:\n{snippet.get('text')}"
        )
        for snippet in snippets
    )
    if not snippet_text:
        snippet_text = "No extracted document text is available. Evaluate from opportunity fields only."

    return f"""
You are evaluating government bid opportunities for a security services company.

Prioritize:
- security services fit
- armed/unarmed/patrol/facility/courthouse/healthcare fit
- location fit: CA, TX, NV, AZ
- due date feasibility
- mandatory pre-bid risk
- licensing risk
- insurance/bonding risk
- unclear scope risk
- as-needed/no guaranteed minimum risk
- proposal effort vs likely value
- whether the opportunity is worth pursuing

Important user preference:
Do not recommend purely as-needed, on-call, standby, bench, task-order-only, or no-guaranteed-minimum contracts as strong pursuits unless there is a guaranteed minimum, clear strategic value, high likelihood of use, or very low response burden.

Accuracy rules:
- Do not invent deadlines, licenses, insurance, values, or requirements.
- If information is missing, put it in missing_information.
- If extracted text is incomplete, say so.
- Return valid JSON only.

Required JSON keys:
{{
  "ai_recommendation": "Bid | Conditional Bid | No Bid | Needs Review",
  "ai_score": 0-100,
  "risk_level": "Low | Medium | High | Disqualifying",
  "pursuit_effort": "Low | Medium | High",
  "reason": "short direct explanation",
  "positive_factors": [],
  "negative_factors": [],
  "missing_information": [],
  "questions_to_verify": [],
  "recommended_next_action": "short direct action"
}}

Rules-based result:
{json.dumps(rules, default=str, indent=2)}

Opportunity fields:
{json.dumps(fields, default=str, indent=2)}

Extracted document text snippets:
{snippet_text}
""".strip()


def load_extracted_text_snippets(
    opportunity_id: int,
    session,
    max_chars: int = 12000,
) -> list[dict]:
    documents = list(
        session.exec(
            select(Document).where(Document.opportunity_id == opportunity_id)
        ).all()
    )
    snippets: list[dict] = []
    remaining = max_chars
    for document in documents:
        if remaining <= 0 or not document.extracted_text_path:
            continue
        path = Path(document.extracted_text_path)
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        snippet = text[:remaining]
        remaining -= len(snippet)
        snippets.append(
            {
                "filename": document.filename,
                "extracted_text_path": document.extracted_text_path,
                "text": snippet,
            }
        )
    return snippets


def evaluate_opportunity_with_local_ai(opportunity_id: int, session) -> dict:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return {"error": "Opportunity not found"}

    rules_result = score_opportunity_text(opportunity)
    snippets = load_extracted_text_snippets(opportunity_id, session)
    prompt = build_opportunity_evaluation_prompt(opportunity, rules_result, snippets)

    try:
        response = generate_json(prompt)
    except LocalAIUnavailableError:
        return {"error": LOCAL_AI_UNAVAILABLE}

    raw_response = response["raw_response"]
    response_text = response["response_text"]
    model_name = response["model"]
    try:
        parsed = parse_ai_json_response(response_text)
    except (ValueError, TypeError) as exc:
        evaluation = _store_error_evaluation(
            opportunity,
            model_name,
            raw_response,
            "Local AI model returned invalid JSON.",
            session,
        )
        return {
            "error": "Local AI model returned invalid JSON.",
            "raw_response": raw_response,
            "evaluation": evaluation,
        }

    evaluation = _store_success_evaluation(
        opportunity,
        model_name,
        parsed,
        raw_response,
        session,
    )
    return {"evaluation": evaluation, "ai_result": parsed}


def parse_ai_json_response(response_text: str) -> dict:
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("AI response was not a JSON object")
    missing = REQUIRED_KEYS - set(data)
    if missing:
        raise ValueError(f"AI response missing keys: {', '.join(sorted(missing))}")
    return _normalize_ai_result(data)


def _store_success_evaluation(
    opportunity: Opportunity,
    model_name: str,
    parsed: dict,
    raw_response: str,
    session,
) -> OpportunityEvaluation:
    evaluation = OpportunityEvaluation(
        opportunity_id=opportunity.id,
        evaluator_type="local_ollama",
        model_name=model_name,
        recommendation=parsed["ai_recommendation"],
        score=float(parsed["ai_score"]),
        risk_level=parsed["risk_level"],
        pursuit_effort=parsed["pursuit_effort"],
        reason=parsed["reason"],
        positive_factors_json=json.dumps(parsed["positive_factors"]),
        negative_factors_json=json.dumps(parsed["negative_factors"]),
        missing_information_json=json.dumps(parsed["missing_information"]),
        questions_to_verify_json=json.dumps(parsed["questions_to_verify"]),
        recommended_next_action=parsed["recommended_next_action"],
        raw_response=raw_response,
    )
    opportunity.ai_recommendation = parsed["ai_recommendation"]
    opportunity.ai_score = float(parsed["ai_score"])
    opportunity.ai_reason = parsed["reason"]
    opportunity.ai_risk_level = parsed["risk_level"]
    opportunity.ai_evaluated_at = _utc_now()
    session.add(evaluation)
    session.add(opportunity)
    session.commit()
    session.refresh(evaluation)
    return evaluation


def _store_error_evaluation(
    opportunity: Opportunity,
    model_name: str,
    raw_response: str,
    reason: str,
    session,
) -> OpportunityEvaluation:
    evaluation = OpportunityEvaluation(
        opportunity_id=opportunity.id,
        evaluator_type="local_ollama",
        model_name=model_name,
        recommendation="Needs Review",
        risk_level="High",
        pursuit_effort="Medium",
        reason=reason,
        raw_response=raw_response,
    )
    session.add(evaluation)
    session.commit()
    session.refresh(evaluation)
    return evaluation


def _normalize_ai_result(data: dict[str, Any]) -> dict:
    result = dict(data)
    result["ai_score"] = max(0, min(100, int(result.get("ai_score", 0))))
    for key in (
        "positive_factors",
        "negative_factors",
        "missing_information",
        "questions_to_verify",
    ):
        value = result.get(key)
        result[key] = value if isinstance(value, list) else []
    for key in (
        "ai_recommendation",
        "risk_level",
        "pursuit_effort",
        "reason",
        "recommended_next_action",
    ):
        result[key] = str(result.get(key, "")).strip()
    return result


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
