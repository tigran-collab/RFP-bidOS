from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from re import sub
from urllib.parse import unquote, urlparse

import requests
from sqlmodel import select

from app.models import Document, Opportunity


DOWNLOADER_USER_AGENT = "RFP-BidOS Document Downloader/0.1 (+direct public URLs)"
DOWNLOAD_ROOT = Path("data/downloads")
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


def download_document(url: str, opportunity_id: int, session) -> dict:
    summary = _empty_summary()

    existing_by_url = session.exec(
        select(Document).where(Document.source_url == url)
    ).first()
    if existing_by_url is not None:
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
    existing_by_hash = session.exec(
        select(Document).where(Document.sha256 == file_hash)
    ).first()
    if existing_by_hash is not None:
        summary["skipped_count"] += 1
        summary["documents"].append(existing_by_hash)
        if existing_by_hash.path != str(path):
            path.unlink(missing_ok=True)
        return summary

    document = Document(
        opportunity_id=opportunity_id,
        filename=path.name,
        path=str(path),
        file_type=path.suffix.lower().lstrip(".") or None,
        sha256=file_hash,
        source_url=url,
        downloaded_at=_utc_now(),
        parsed_status="Not Parsed",
    )
    session.add(document)
    session.commit()
    session.refresh(document)

    summary["downloaded_count"] += 1
    summary["documents"].append(document)
    return summary


def download_documents_for_opportunity(opportunity_id: int, session) -> dict:
    summary = _empty_summary()
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        summary["errors"].append("Opportunity not found")
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
