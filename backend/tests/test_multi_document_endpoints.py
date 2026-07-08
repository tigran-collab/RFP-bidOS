"""H4: multi-document endpoints must return every document fully populated.

Before the fix, per-document commits expired previously-refreshed ORM
instances, so all entries but the last serialized as {} once the session
closed. These tests process >=2 documents and assert each returned entry is
fully populated.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (register tables)
from app.main import app
from app.models import Document, Opportunity
from app.services import parser


@pytest.fixture
def multi_doc_client(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.routers.opportunities.engine", engine, raising=True)
    monkeypatch.setattr("app.routers.documents.engine", engine, raising=True)
    monkeypatch.setattr(parser, "PROCESSED_ROOT", tmp_path / "processed", raising=True)
    client = TestClient(app)
    client._engine = engine
    client._root = tmp_path
    return client


def _seed_two_downloaded_docs(client):
    with Session(client._engine) as session:
        opportunity = Opportunity(title="Security Guard Services")
        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        ids = []
        for index in (1, 2):
            file_path = client._root / f"doc{index}.txt"
            file_path.write_text(
                f"Requirement text number {index} with plenty of real characters."
            )
            document = Document(
                opportunity_id=opportunity.id,
                filename=f"doc{index}.txt",
                path=str(file_path),
                file_type="txt",
                parsed_status="Not Parsed",
            )
            session.add(document)
            session.commit()
            session.refresh(document)
            ids.append(document.id)
        return opportunity.id, ids


def test_parse_documents_returns_all_documents_populated(multi_doc_client):
    opportunity_id, ids = _seed_two_downloaded_docs(multi_doc_client)

    response = multi_doc_client.post(
        f"/opportunities/{opportunity_id}/parse-documents"
    )

    assert response.status_code == 200
    documents = response.json()["documents"]
    assert len(documents) == 2
    for document in documents:
        assert document.get("id") in ids
        assert document.get("filename")
        assert document.get("parsed_status") == "Parsed"


def test_parse_all_returns_all_documents_populated(multi_doc_client):
    _seed_two_downloaded_docs(multi_doc_client)

    response = multi_doc_client.post("/documents/parse-all")

    assert response.status_code == 200
    documents = response.json()["documents"]
    assert len(documents) == 2
    assert all(document.get("filename") for document in documents)
    assert all(document.get("parsed_status") == "Parsed" for document in documents)
