from pathlib import Path

from app import config
from app.services import downloader, parser
from app.services.scrapers import authenticated_browser, planetbids


def test_default_database_url_is_backend_rooted(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    settings = config.Settings(_env_file=None)
    db_path = config.sqlite_file_path_from_url(settings.database_url)

    assert db_path == config.DEFAULT_DATABASE_PATH


def test_relative_sqlite_database_url_is_resolved_from_backend_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    url = config.resolve_sqlite_database_url("sqlite:///./data/test.db")
    db_path = config.sqlite_file_path_from_url(url)

    assert db_path == config.BACKEND_ROOT / "data" / "test.db"


def test_non_file_database_urls_are_not_rewritten():
    assert config.resolve_sqlite_database_url("sqlite://") == "sqlite://"
    assert config.resolve_sqlite_database_url("sqlite:///:memory:") == "sqlite:///:memory:"
    assert config.resolve_sqlite_database_url("postgresql://localhost/app") == (
        "postgresql://localhost/app"
    )


def test_runtime_data_paths_are_backend_rooted():
    assert config.DOWNLOAD_ROOT == config.DATA_ROOT / "downloads"
    assert config.PROCESSED_ROOT == config.DATA_ROOT / "processed"
    assert config.BROWSER_PROFILE_ROOT == config.DATA_ROOT / "browser_profiles"
    assert downloader.DOWNLOAD_ROOT == config.DOWNLOAD_ROOT
    assert parser.PROCESSED_ROOT == config.PROCESSED_ROOT


def test_authenticated_profile_paths_use_backend_data_root():
    class Source:
        id = 42

    expected = str(config.BROWSER_PROFILE_ROOT / "42")

    assert planetbids.profile_dir_for_source(Source()) == expected
    assert authenticated_browser.profile_dir_for_source(Source()) == expected
