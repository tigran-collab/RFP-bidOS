"""Tests for the Media Gallery: upload/validation, metadata, listing/filtering,
permissions, safe file access, archival, and deletion."""

import base64

import pytest

from app.services.kb import gallery
from app.services.kb.permissions import KbPermissionError
from tests.kb_factories import make_admin, make_entity, make_reader

# A valid 1x1 transparent PNG.
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'


@pytest.fixture(autouse=True)
def _isolate_gallery_root(tmp_path, monkeypatch):
    """Redirect stored files to a temp dir so tests never touch data/kb_gallery/."""
    monkeypatch.setattr(gallery, "KB_GALLERY_ROOT", tmp_path)


def test_upload_png_stores_and_reads_dimensions(session):
    admin = make_admin(session)
    entity = make_entity(session)
    asset = gallery.create_asset(
        session, admin, filename="logo.png", content=PNG_1x1,
        metadata={"title": "Company Logo", "category": "Logo", "company_entity_id": entity.id},
    )
    assert asset.id is not None
    assert asset.file_type == "png"
    assert asset.mime_type == "image/png"
    assert asset.title == "Company Logo"
    assert asset.category == "Logo"
    # Pillow may or may not be installed; if present, dimensions are captured.
    assert asset.width in (1, None)
    # The stored file resolves safely under the gallery root.
    assert gallery.resolve_asset_file(asset) is not None


def test_upload_svg_is_accepted(session):
    admin = make_admin(session)
    asset = gallery.create_asset(
        session, admin, filename="mark.svg", content=SVG, metadata={"category": "Logo Mark / Icon"},
    )
    assert asset.file_type == "svg"
    assert asset.mime_type == "image/svg+xml"


def test_reject_non_image_content(session):
    admin = make_admin(session)
    with pytest.raises(gallery.GalleryAssetError):
        gallery.create_asset(
            session, admin, filename="fake.png", content=b"this is not an image",
        )


def test_reject_unsupported_extension(session):
    admin = make_admin(session)
    with pytest.raises(gallery.GalleryAssetError):
        gallery.create_asset(session, admin, filename="doc.pdf", content=b"%PDF-1.4")


def test_reject_empty_file(session):
    admin = make_admin(session)
    with pytest.raises(gallery.GalleryAssetError):
        gallery.create_asset(session, admin, filename="empty.png", content=b"")


def test_reject_oversized(session, monkeypatch):
    admin = make_admin(session)
    monkeypatch.setattr(gallery, "MAX_GALLERY_BYTES", 4)
    with pytest.raises(gallery.GalleryAssetError):
        gallery.create_asset(session, admin, filename="logo.png", content=PNG_1x1)


def test_read_only_cannot_upload(session):
    reader = make_reader(session)
    with pytest.raises(KbPermissionError):
        gallery.create_asset(session, reader, filename="logo.png", content=PNG_1x1)


def test_read_only_cannot_delete(session):
    admin = make_admin(session)
    reader = make_reader(session)
    asset = gallery.create_asset(session, admin, filename="logo.png", content=PNG_1x1)
    with pytest.raises(KbPermissionError):
        gallery.delete_asset(session, reader, asset.id)


def test_list_filters_by_category_and_archived(session):
    admin = make_admin(session)
    logo = gallery.create_asset(session, admin, filename="a.png", content=PNG_1x1, metadata={"category": "Logo"})
    badge = gallery.create_asset(session, admin, filename="badge.svg", content=SVG, metadata={"category": "Certification Badge"})

    logos = gallery.list_assets(session, category="Logo")
    assert [a.id for a in logos] == [logo.id]

    gallery.archive_asset(session, admin, badge.id, True)
    active = gallery.list_assets(session, archived=False)
    assert badge.id not in [a.id for a in active]
    archived = gallery.list_assets(session, archived=True)
    assert badge.id in [a.id for a in archived]


def test_update_metadata_and_tags(session):
    admin = make_admin(session)
    asset = gallery.create_asset(session, admin, filename="logo.png", content=PNG_1x1)
    updated = gallery.update_asset(
        session, admin, asset.id,
        {"title": "Primary Logo", "alt_text": "Aventus logo", "tags": ["brand", "primary"]},
    )
    assert updated.title == "Primary Logo"
    assert updated.alt_text == "Aventus logo"
    d = gallery.asset_to_dict(updated)
    assert d["tags"] == ["brand", "primary"]


def test_delete_removes_row(session):
    admin = make_admin(session)
    asset = gallery.create_asset(session, admin, filename="logo.png", content=PNG_1x1)
    gallery.delete_asset(session, admin, asset.id)
    with pytest.raises(gallery.GalleryAssetNotFoundError):
        gallery.get_asset(session, asset.id)


def test_expiration_flag_in_dict(session):
    from datetime import timedelta

    from app.models import utcnow_naive

    admin = make_admin(session)
    past = (utcnow_naive() - timedelta(days=1)).isoformat()
    asset = gallery.create_asset(
        session, admin, filename="cert.png", content=PNG_1x1,
        metadata={"category": "Certification Badge", "expiration_date": past},
    )
    assert gallery.asset_to_dict(asset)["expired"] is True
