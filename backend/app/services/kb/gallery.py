"""Media Gallery service: secure storage of reusable visual assets (logos,
badges, photos, diagrams), metadata, listing/filtering, archival, and safe file
access.

Unlike the Source Document Vault, gallery assets are displayed/reused as images
rather than text-extracted into claims. Uploaded files are validated (extension
+ size + MIME + image magic bytes), stored under ``data/kb_gallery/`` with a
content hash, and served by id. Image dimensions are read with Pillow when it is
installed (optional, lazily imported); without it, assets still upload and
display and dimensions are simply left unset.
"""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from re import sub
from typing import Any

from sqlmodel import Session, select

from app.config import KB_GALLERY_ROOT
from app.kb_models import GalleryAsset, KbUser, utcnow_naive
from app.kb_vocab import (
    GALLERY_IMAGE_EXTS,
    GALLERY_MIME_BY_EXT,
    PERM_ARCHIVE_DOCUMENTS,
    PERM_EDIT_METADATA,
    PERM_UPLOAD_DOCUMENTS,
)
from app.services.kb.audit import record_audit
from app.services.kb.permissions import require_permission

# Images are far smaller than source documents; keep the cap tight.
MAX_GALLERY_BYTES = 25 * 1024 * 1024

_META_SCALARS = (
    "title",
    "category",
    "company_entity_id",
    "description",
    "alt_text",
)
_META_DATES = ("effective_date", "expiration_date", "last_reviewed_at")


class GalleryAssetError(RuntimeError):
    status_code = 400


class GalleryAssetNotFoundError(RuntimeError):
    status_code = 404


def _parse_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _safe_filename(name: str, fallback: str = "asset") -> str:
    cleaned = sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("._")
    return cleaned or fallback


def _ext_of(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _looks_like_image(content: bytes, ext: str) -> bool:
    """Best-effort magic-byte check so a non-image renamed with an image
    extension is rejected. SVG is text, so it is matched structurally."""
    head = content[:64]
    if ext == "svg":
        lowered = head.lstrip().lower()
        return lowered.startswith(b"<?xml") or b"<svg" in content[:1024].lower()
    signatures = (
        head.startswith(b"\x89PNG\r\n\x1a\n"),          # png
        head[:3] == b"\xff\xd8\xff",                     # jpg/jpeg
        head[:6] in (b"GIF87a", b"GIF89a"),              # gif
        head[:4] == b"RIFF" and content[8:12] == b"WEBP",  # webp
        head[:2] == b"BM",                                # bmp
    )
    return any(signatures)


def _image_dimensions(content: bytes, ext: str) -> tuple[int | None, int | None]:
    """Return (width, height) using Pillow if available; else (None, None).

    Pillow is optional (not a hard dependency); SVG is vector and skipped."""
    if ext == "svg":
        return (None, None)
    try:
        import io

        from PIL import Image  # optional dependency

        with Image.open(io.BytesIO(content)) as img:
            return (int(img.width), int(img.height))
    except Exception:
        return (None, None)


def create_asset(
    session: Session,
    actor: KbUser,
    *,
    filename: str,
    content: bytes,
    metadata: dict | None = None,
) -> GalleryAsset:
    """Validate and store an uploaded image, returning the new asset row."""
    require_permission(actor, PERM_UPLOAD_DOCUMENTS)
    metadata = metadata or {}

    ext = _ext_of(filename) or (metadata.get("mime_type") or "").split("/")[-1]
    if ext == "jpe":
        ext = "jpeg"
    if ext not in GALLERY_IMAGE_EXTS:
        raise GalleryAssetError(
            f"Unsupported image type '{ext or 'unknown'}'. "
            f"Supported: {', '.join(GALLERY_IMAGE_EXTS)}."
        )
    if not content:
        raise GalleryAssetError("Uploaded file is empty.")
    if len(content) > MAX_GALLERY_BYTES:
        raise GalleryAssetError(
            f"Image exceeds the maximum size of {MAX_GALLERY_BYTES // (1024 * 1024)} MB."
        )
    if not _looks_like_image(content, ext):
        raise GalleryAssetError(
            f"File does not appear to be a valid {ext.upper()} image."
        )

    digest = sha256(content).hexdigest()
    safe_name = _safe_filename(Path(filename).name, fallback=f"asset.{ext}")
    KB_GALLERY_ROOT.mkdir(parents=True, exist_ok=True)
    stored_name = f"{digest[:16]}_{safe_name}"
    target = KB_GALLERY_ROOT / stored_name
    if not target.exists():
        target.write_bytes(content)

    width, height = _image_dimensions(content, ext)
    now = utcnow_naive()
    asset = GalleryAsset(
        title=str(metadata.get("title") or Path(filename).stem or safe_name).strip(),
        filename=safe_name,
        path=str(target),
        file_type=ext,
        mime_type=metadata.get("mime_type") or GALLERY_MIME_BY_EXT.get(ext),
        sha256=digest,
        size_bytes=len(content),
        width=width,
        height=height,
        category=metadata.get("category"),
        company_entity_id=metadata.get("company_entity_id"),
        tags_json=json.dumps(metadata.get("tags") or []) or None,
        description=metadata.get("description"),
        alt_text=metadata.get("alt_text"),
        effective_date=_parse_date(metadata.get("effective_date")),
        expiration_date=_parse_date(metadata.get("expiration_date")),
        uploaded_by=actor.id,
        uploaded_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    record_audit(
        session, actor, "gallery.upload", target_type="gallery_asset",
        target_id=asset.id, detail={"filename": safe_name, "sha256": digest},
    )
    return asset


def get_asset(session: Session, asset_id: int) -> GalleryAsset:
    asset = session.get(GalleryAsset, asset_id)
    if asset is None:
        raise GalleryAssetNotFoundError(f"Gallery asset {asset_id} not found")
    return asset


def list_assets(
    session: Session,
    *,
    category: str | None = None,
    company_entity_id: int | None = None,
    tag: str | None = None,
    archived: bool | None = False,
    limit: int = 500,
) -> list[GalleryAsset]:
    assets = list(session.exec(select(GalleryAsset)).all())
    out = []
    for a in assets:
        if archived is not None and bool(a.archived) != bool(archived):
            continue
        if category and a.category != category:
            continue
        if company_entity_id is not None and a.company_entity_id != company_entity_id:
            continue
        if tag:
            tags = json.loads(a.tags_json) if a.tags_json else []
            if tag.lower() not in [str(t).lower() for t in tags]:
                continue
        out.append(a)
    out.sort(key=lambda a: a.id or 0, reverse=True)
    return out[:limit]


def update_asset(
    session: Session, actor: KbUser, asset_id: int, payload: dict
) -> GalleryAsset:
    require_permission(actor, PERM_EDIT_METADATA)
    asset = get_asset(session, asset_id)
    for field in _META_SCALARS:
        if field in payload:
            setattr(asset, field, payload[field])
    for field in _META_DATES:
        if field in payload:
            setattr(asset, field, _parse_date(payload[field]))
    if "tags" in payload:
        asset.tags_json = json.dumps(payload.get("tags") or []) or None
    asset.updated_at = utcnow_naive()
    session.add(asset)
    session.commit()
    session.refresh(asset)
    record_audit(
        session, actor, "gallery.update", target_type="gallery_asset",
        target_id=asset.id, detail={"fields": sorted(payload.keys())},
    )
    return asset


def archive_asset(
    session: Session, actor: KbUser, asset_id: int, archived: bool = True
) -> GalleryAsset:
    require_permission(actor, PERM_ARCHIVE_DOCUMENTS)
    asset = get_asset(session, asset_id)
    asset.archived = archived
    asset.updated_at = utcnow_naive()
    session.add(asset)
    session.commit()
    session.refresh(asset)
    record_audit(
        session, actor, "gallery.archive", target_type="gallery_asset",
        target_id=asset.id, detail={"archived": archived},
    )
    return asset


def resolve_asset_file(asset: GalleryAsset) -> Path | None:
    """Return a safe existing path for the stored image, or None (guards against
    path traversal by requiring the resolved path to live under the gallery root)."""
    if not asset.path:
        return None
    path = Path(asset.path)
    try:
        resolved = path.resolve()
        root = KB_GALLERY_ROOT.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def delete_asset(session: Session, actor: KbUser, asset_id: int) -> None:
    require_permission(actor, PERM_ARCHIVE_DOCUMENTS)
    asset = get_asset(session, asset_id)
    stored = resolve_asset_file(asset)
    # Only remove the stored file if no other asset row references it (dedup by
    # content hash means two rows can point at the same file).
    if stored is not None:
        others = session.exec(
            select(GalleryAsset).where(
                GalleryAsset.sha256 == asset.sha256, GalleryAsset.id != asset_id
            )
        ).first()
        if others is None:
            try:
                stored.unlink()
            except OSError:
                pass
    session.delete(asset)
    session.commit()
    record_audit(
        session, actor, "gallery.delete", target_type="gallery_asset", target_id=asset_id
    )


def asset_to_dict(asset: GalleryAsset) -> dict:
    now = utcnow_naive()
    expired = bool(asset.expiration_date and asset.expiration_date < now)
    return {
        "id": asset.id,
        "title": asset.title,
        "filename": asset.filename,
        "file_type": asset.file_type,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "width": asset.width,
        "height": asset.height,
        "category": asset.category,
        "company_entity_id": asset.company_entity_id,
        "tags": json.loads(asset.tags_json) if asset.tags_json else [],
        "description": asset.description,
        "alt_text": asset.alt_text,
        "effective_date": asset.effective_date.isoformat() if asset.effective_date else None,
        "expiration_date": asset.expiration_date.isoformat() if asset.expiration_date else None,
        "expired": expired,
        "uploaded_by": asset.uploaded_by,
        "uploaded_at": asset.uploaded_at.isoformat() if asset.uploaded_at else None,
        "archived": asset.archived,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }
