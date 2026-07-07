from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from re import sub
from urllib.parse import unquote, urlparse

import requests
from sqlmodel import select

from app.config import BACKEND_ROOT, DOWNLOAD_ROOT
from app.models import Document, Opportunity


DOWNLOADER_USER_AGENT = "RFP-BidOS Document Downloader/0.1 (+direct public URLs)"
DOWNLOADABLE_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".zip",
}
DOWNLOADABLE_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/csv": ".csv",
    "application/csv": ".csv",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
}


def is_downloadable_url(url: str) -> bool:
    parsed = urlparse(url)
    suffix = Path(unquote(parsed.path)).suffix.lower()
    return suffix in DOWNLOADABLE_EXTENSIONS


def safe_filename_from_url(url: str, fallback: str = "document") -> str:
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name or fallback
    name = sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def sha256_file(path: str) -> str:
    digest = sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_downloaded_document_path(document: Document) -> Path | None:
    """Return a safe existing local file path for a downloaded document."""
    if not document.path:
        return None
    path = Path(document.path)
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    try:
        resolved = path.resolve()
        root = DOWNLOAD_ROOT.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return resolved


def download_document(url: str, opportunity_id: int, session) -> dict:
    summary = _empty_summary()

    # Scope to this opportunity: the same URL can belong to multiple
    # opportunities, and we must never reassign another opportunity's document.
    existing_by_url = session.exec(
        select(Document).where(
            Document.source_url == url,
            Document.opportunity_id == opportunity_id,
        )
    ).first()
    if (
        existing_by_url is not None
        and existing_by_url.path
        and resolve_downloaded_document_path(existing_by_url) is not None
    ):
        summary["skipped_count"] += 1
        summary["documents"].append(existing_by_url)
        return summary

    try:
        response = requests.get(
            url,
            headers={"User-Agent": DOWNLOADER_USER_AGENT},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        summary["errors"].append(str(exc))
        return summary

    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    if not is_downloadable_url(url) and content_type not in DOWNLOADABLE_CONTENT_TYPES:
        summary["skipped_count"] += 1
        summary["errors"].append("Source URL is not a supported document URL")
        return summary

    filename = safe_filename_from_url(url)
    filename = _ensure_extension(filename, content_type)
    directory = DOWNLOAD_ROOT / f"opportunity_{opportunity_id}"
    directory.mkdir(parents=True, exist_ok=True)
    path = _available_path(directory / filename, response.content)
    path.write_bytes(response.content)

    file_hash = sha256_file(str(path))
    # Dedupe identical content within the same opportunity only, so each
    # opportunity keeps its own self-contained document set.
    existing_by_hash = session.exec(
        select(Document).where(
            Document.sha256 == file_hash,
            Document.opportunity_id == opportunity_id,
        )
    ).first()
    if existing_by_hash is not None:
        summary["skipped_count"] += 1
        summary["documents"].append(existing_by_hash)
        if existing_by_hash.path != str(path):
            path.unlink(missing_ok=True)
        if existing_by_url is not None and existing_by_url.id != existing_by_hash.id:
            session.delete(existing_by_url)
            session.commit()
        return summary

    document = existing_by_url or Document(
        opportunity_id=opportunity_id,
        filename="",
        path="",
        source_url=url,
    )
    document.opportunity_id = opportunity_id
    document.filename = path.name
    document.path = str(path)
    document.file_type = path.suffix.lower().lstrip(".") or None
    document.sha256 = file_hash
    document.source_url = url
    document.downloaded_at = _utc_now()
    document.parsed_status = "Not Parsed"
    session.add(document)
    session.commit()
    session.refresh(document)

    summary["downloaded_count"] += 1
    summary["documents"].append(document)
    return summary


def download_document_by_id(document_id: int, session) -> dict:
    summary = _empty_summary()
    document = session.get(Document, document_id)
    if document is None:
        summary["errors"].append("Document not found")
        return summary
    if not document.source_url:
        summary["skipped_count"] += 1
        summary["errors"].append("Document has no source_url")
        summary["documents"].append(document)
        return summary
    return download_document(document.source_url, document.opportunity_id, session)


def download_documents_for_opportunity(opportunity_id: int, session) -> dict:
    summary = _empty_summary()
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        summary["errors"].append("Opportunity not found")
        return summary

    known_documents = list(
        session.exec(
            select(Document).where(
                Document.opportunity_id == opportunity_id,
                Document.source_url != None,
            )
        ).all()
    )
    if known_documents:
        documents_to_download = [
            document
            for document in known_documents
            if not document.path or resolve_downloaded_document_path(document) is None
        ]
        if not documents_to_download:
            summary["skipped_count"] += len(known_documents)
            summary["documents"].extend(known_documents)
            return summary

        for document in documents_to_download:
            result = download_document(document.source_url, opportunity_id, session)
            summary = _merge_summary(summary, result)
        return summary

    if not opportunity.source_url:
        summary["skipped_count"] += 1
        summary["errors"].append("Opportunity has no source_url")
        return summary

    if not is_downloadable_url(opportunity.source_url):
        summary["skipped_count"] += 1
        summary["errors"].append("Opportunity source_url is not a direct document URL")
        return summary

    result = download_document(opportunity.source_url, opportunity_id, session)
    return _merge_summary(summary, result)


def _empty_summary() -> dict:
    return {
        "downloaded_count": 0,
        "skipped_count": 0,
        "errors": [],
        "documents": [],
    }


def _merge_summary(summary: dict, result: dict) -> dict:
    summary["downloaded_count"] += result["downloaded_count"]
    summary["skipped_count"] += result["skipped_count"]
    summary["errors"].extend(result["errors"])
    summary["documents"].extend(result["documents"])
    return summary


def _ensure_extension(filename: str, content_type: str) -> str:
    if Path(filename).suffix:
        return filename
    extension = DOWNLOADABLE_CONTENT_TYPES.get(content_type)
    if extension:
        return f"{filename}{extension}"
    return filename


def _available_path(path: Path, content: bytes) -> Path:
    if not path.exists():
        return path

    existing_hash = sha256_file(str(path))
    content_hash = sha256(content).hexdigest()
    if existing_hash == content_hash:
        return path

    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError("Could not create a non-conflicting document filename")


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
