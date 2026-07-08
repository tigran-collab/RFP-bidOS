"""Config tests: Settings must ignore unknown .env keys.

pydantic-settings forbids extras by default, which crashed startup when
backend/.env carried any key the Settings model didn't declare.
"""

from app.config import Settings


def test_settings_ignores_unknown_env_keys(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OLLAMA_MODEL=custom:latest\n"
        "BIDNET_USERNAME=someone\n"
        "RFP_BIDOS_BROWSER_CHANNEL=chrome\n"
        "SOME_TOTALLY_UNKNOWN_KEY=whatever\n",
        encoding="utf-8",
    )
    # Ensure no stray process env vars shadow the file values.
    for key in ("OLLAMA_MODEL", "BIDNET_USERNAME", "SOME_TOTALLY_UNKNOWN_KEY"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=str(env_file))

    # Does not raise on the extra keys, and declared fields still load.
    assert settings.ollama_model == "custom:latest"
