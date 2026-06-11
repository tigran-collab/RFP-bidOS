from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import select

from app.models import Document


PROCESSED_ROOT = Path("data/processed")
PDF_TYPES = {"pdf", ".pdf", "application/pdf"}
TXT_TYPES = {"txt", ".txt", "text/plain"}


def parse_pdf_to_text(document_id: int, session) -> dict:
    document = session.get(Document, document_id)
    if document is None:
        return _result(document_id=document_id, status="Parse Failed", errors=["Document not found"])

    output_path = _output_path(document)
    try:
        parser_used, page_count = _parse_pdf_with_pypdf(document.path, output_path)
    except Exception as pypdf_exc:
        try:
            parser_used, page_count = _parse_pdf_with_pymupdf(document.path, output_path)
        except Exception as pymupdf_exc:
            parse_error = (
                f"pypdf failed: {pypdf_exc}; "
                f"PyMuPDF fallback failed: {pymupdf_exc}"
            )
            document.parsed_status = "Parse Failed"
            document.parsed_at = _utc_now()
            session.add(document)
            session.commit()
            return _result(
                document_id=document_id,
                status="Parse Failed",
                errors=[parse_error],
                parse_error=parse_error,
                parsed_status="Parse Failed",
            )

    document.parsed_status = "Parsed"
    document.extracted_text_path = str(output_path)
    document.page_count = page_count
    document.parsed_at = _utc_now()
    session.add(document)
    session.commit()
    session.refresh(document)
    return _result(
        document_id=document_id,
        status="Parsed",
        parsed_count=1,
        documents=[document],
        extracted_text_path=str(output_path),
        page_count=page_count,
        parser_used=parser_used,
        parsed_status="Parsed",
    )


def parse_document(document_id: int, session) -> dict:
    document = session.get(Document, document_id)
    if document is None:
        return _result(document_id=document_id, status="Parse Failed", errors=["Document not found"])

    file_type = (document.file_type or Path(document.path).suffix).lower()
    if file_type in PDF_TYPES:
        return parse_pdf_to_text(document_id, session)
    if file_type in TXT_TYPES:
        return _parse_txt_to_text(document, session)

    document.parsed_status = "Unsupported File Type"
    document.parsed_at = _utc_now()
    session.add(document)
    session.commit()
    session.refresh(document)
    return _result(
        document_id=document_id,
        status="Unsupported File Type",
        skipped_count=1,
        documents=[document],
        parsed_status="Unsupported File Type",
    )


def parse_documents_for_opportunity(opportunity_id: int, session) -> dict:
    documents = list(
        session.exec(
            select(Document).where(Document.opportunity_id == opportunity_id)
        ).all()
    )
    summary = _summary()
    for document in documents:
        _merge(summary, parse_document(document.id, session))
    return summary


def parse_all_documents(session) -> dict:
    documents = list(session.exec(select(Document)).all())
    summary = _summary()
    for document in documents:
        _merge(summary, parse_document(document.id, session))
    return summary


def _parse_txt_to_text(document: Document, session) -> dict:
    output_path = _output_path(document)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        text = Path(document.path).read_text(encoding="utf-8", errors="replace")
        output_path.write_text("--- Page 1 ---\n" + text + "\n", encoding="utf-8")

        document.parsed_status = "Parsed"
        document.extracted_text_path = str(output_path)
        document.page_count = 1
        document.parsed_at = _utc_now()
        session.add(document)
        session.commit()
        session.refresh(document)
        return _result(
            document_id=document.id,
            status="Parsed",
            parsed_count=1,
            documents=[document],
            extracted_text_path=str(output_path),
            page_count=1,
            parser_used="text",
            parsed_status="Parsed",
        )
    except Exception as exc:
        document.parsed_status = "Parse Failed"
        document.parsed_at = _utc_now()
        session.add(document)
        session.commit()
        return _result(
            document_id=document.id,
            status="Parse Failed",
            errors=[str(exc)],
            parse_error=str(exc),
            parsed_status="Parse Failed",
        )


def _parse_pdf_with_pypdf(input_path: str, output_path: Path) -> tuple[str, int]:
    from pypdf import PdfReader

    output_path.parent.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(input_path)
    with output_path.open("w", encoding="utf-8") as output:
        for page_index, page in enumerate(reader.pages, start=1):
            output.write(f"--- Page {page_index} ---\n")
            output.write(page.extract_text() or "")
            output.write("\n\n")
    return "pypdf", len(reader.pages)


def _parse_pdf_with_pymupdf(input_path: str, output_path: Path) -> tuple[str, int]:
    try:
        import fitz
    except Exception as exc:
        raise RuntimeError(
            "PyMuPDF/fitz could not load. It is optional; pypdf is the default parser."
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(input_path) as pdf:
        page_count = pdf.page_count
        with output_path.open("w", encoding="utf-8") as output:
            for page_index, page in enumerate(pdf, start=1):
                output.write(f"--- Page {page_index} ---\n")
                output.write(page.get_text())
                output.write("\n\n")
    return "pymupdf", page_count


def _output_path(document: Document) -> Path:
    return (
        PROCESSED_ROOT
        / f"opportunity_{document.opportunity_id}"
        / f"document_{document.id}.txt"
    )


def _summary() -> dict:
    return {
        "parsed_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "errors": [],
        "documents": [],
    }


def _result(
    document_id: int | None,
    status: str,
    parsed_count: int = 0,
    skipped_count: int = 0,
    errors: list[str] | None = None,
    documents: list[Document] | None = None,
    extracted_text_path: str | None = None,
    page_count: int | None = None,
    parser_used: str | None = None,
    parsed_status: str | None = None,
    parse_error: str | None = None,
) -> dict:
    failed_count = 1 if status == "Parse Failed" else 0
    return {
        "document_id": document_id,
        "status": status,
        "parsed_count": parsed_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "errors": errors or [],
        "documents": documents or [],
        "extracted_text_path": extracted_text_path,
        "page_count": page_count,
        "parser_used": parser_used,
        "parsed_status": parsed_status or status,
        "parse_error": parse_error,
    }


def _merge(summary: dict, result: dict) -> dict:
    summary["parsed_count"] += result["parsed_count"]
    summary["skipped_count"] += result["skipped_count"]
    summary["failed_count"] += result["failed_count"]
    summary["errors"].extend(result["errors"])
    summary["documents"].extend(result["documents"])
    return summary


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
