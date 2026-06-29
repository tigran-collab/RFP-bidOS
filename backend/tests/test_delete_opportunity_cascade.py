"""Regression test for deleting an opportunity and its child rows.

The delete route opens its own Session(engine), so this exercises the same
deletion logic against the offline in-memory `session` fixture to confirm no
Document/Requirement/OpportunityEvaluation/BidLogisticsQA rows are orphaned.
"""

from sqlmodel import select

from app.models import (
    BidLogisticsQA,
    Document,
    Opportunity,
    OpportunityEvaluation,
    Requirement,
)


def _delete_opportunity_with_children(session, opportunity_id: int) -> None:
    # Mirrors app.routers.opportunities.delete_opportunity.
    opportunity = session.get(Opportunity, opportunity_id)
    assert opportunity is not None
    for child_model in (Document, Requirement, OpportunityEvaluation, BidLogisticsQA):
        children = session.exec(
            select(child_model).where(child_model.opportunity_id == opportunity_id)
        ).all()
        for child in children:
            session.delete(child)
    session.delete(opportunity)
    session.commit()


def test_delete_opportunity_removes_all_children(session):
    opportunity = Opportunity(title="Security Guard Services", source="Manual")
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)
    opp_id = opportunity.id

    session.add(Document(opportunity_id=opp_id, filename="rfp.pdf", path="rfp.pdf"))
    session.add(Requirement(opportunity_id=opp_id, requirement_text="Provide insurance"))
    session.add(OpportunityEvaluation(opportunity_id=opp_id, evaluator_type="local_ai"))
    session.add(BidLogisticsQA(opportunity_id=opp_id, qa_status="Passed", risk_level="Low"))
    session.commit()

    # Sanity: children exist before delete.
    for model in (Document, Requirement, OpportunityEvaluation, BidLogisticsQA):
        rows = session.exec(select(model).where(model.opportunity_id == opp_id)).all()
        assert len(rows) == 1

    _delete_opportunity_with_children(session, opp_id)

    assert session.get(Opportunity, opp_id) is None
    for model in (Document, Requirement, OpportunityEvaluation, BidLogisticsQA):
        rows = session.exec(select(model).where(model.opportunity_id == opp_id)).all()
        assert rows == [], f"{model.__name__} rows were orphaned"
