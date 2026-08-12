"""Typed config loading for config/config.yaml, companies.yaml, profile.yaml.

Three layers:

- `Settings` — environment-only (JOBBOARD_DB, OLLAMA_HOST, API keys). These
  are the values the systemd unit sets explicitly so dev and the scheduled
  run never collide (CLAUDE.md "Data handling").
- `AppConfig` — config/config.yaml: sources, scoring, filters, model names.
- `CompanyConfig` / `ProfileConfig` — config/companies.yaml and
  config/profile.yaml, both gitignored (user data, not checked in).

Any malformed file raises `ConfigError` with the file path and the
underlying validation errors — callers (CLI, doctor) surface it directly
rather than swallowing it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Raised on a missing or malformed config file. Message is user-facing."""


def default_config_dir() -> Path:
    return Path("config")


class Settings(BaseSettings):
    """Environment-sourced settings. Never hardcode these values elsewhere."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    database_path: Path = Field(default=Path("data/jobs.db"), validation_alias="JOBBOARD_DB")
    ollama_host: str = Field(
        default="http://127.0.0.1:11434", validation_alias="OLLAMA_HOST"
    )
    config_dir: Path = Field(
        default_factory=default_config_dir, validation_alias="JOBBOARD_CONFIG_DIR"
    )
    usajobs_api_key: str | None = Field(default=None, validation_alias="USAJOBS_API_KEY")
    usajobs_user_agent_email: str | None = Field(
        default=None, validation_alias="USAJOBS_USER_AGENT_EMAIL"
    )
    adzuna_app_id: str | None = Field(default=None, validation_alias="ADZUNA_APP_ID")
    adzuna_app_key: str | None = Field(default=None, validation_alias="ADZUNA_APP_KEY")
    ntfy_url: str | None = Field(default=None, validation_alias="NTFY_URL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


class OllamaConfig(BaseModel):
    embed_model: str = "nomic-embed-text"
    chat_model: str = "qwen2.5:14b"
    keep_alive: str = "30m"


class SourceToggle(BaseModel):
    enabled: bool = False


class ScoringConfig(BaseModel):
    top_n: int = 40
    scorer_version_prefix: str = "v1"


class FiltersConfig(BaseModel):
    max_age_days: int = 30
    locations: list[str] = Field(default_factory=list)
    exclude_titles: list[str] = Field(default_factory=list)
    exclude_companies: list[str] = Field(default_factory=list)
    seniority_band: list[str] = Field(default_factory=list)
    salary_floor: int | None = None
    require_us_work_auth_ok: bool = True


class AppConfig(BaseModel):
    ollama: OllamaConfig = OllamaConfig()
    sources: dict[str, SourceToggle] = Field(default_factory=dict)
    scoring: ScoringConfig = ScoringConfig()
    filters: FiltersConfig = FiltersConfig()


class CompanyConfig(BaseModel):
    name: str
    ats: str
    slug: str
    tags: list[str] = Field(default_factory=list)


class HardConstraints(BaseModel):
    locations: list[str] = Field(default_factory=list)
    remote_only: bool = False
    comp_floor: int | None = None
    work_authorization: str | None = None
    clearance: str | None = None
    industries_to_avoid: list[str] = Field(default_factory=list)


class ProfileConfig(BaseModel):
    seniority_band: str | None = None
    total_relevant_years: float | None = None
    domains: list[str] = Field(default_factory=list)
    hard_constraints: HardConstraints = HardConstraints()


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML\n{exc}") from exc


def _load_model[T: BaseModel](path: Path, model: type[T]) -> T:
    data = _read_yaml(path)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: invalid config\n{exc}") from exc


def load_app_config(path: Path | None = None) -> AppConfig:
    path = path or (get_settings().config_dir / "config.yaml")
    return _load_model(path, AppConfig)


def load_companies(path: Path | None = None) -> list[CompanyConfig]:
    path = path or (get_settings().config_dir / "companies.yaml")
    data = _read_yaml(path)
    try:
        return [CompanyConfig.model_validate(c) for c in data.get("companies", [])]
    except ValidationError as exc:
        raise ConfigError(f"{path}: invalid config\n{exc}") from exc


def load_profile(path: Path | None = None) -> ProfileConfig:
    path = path or (get_settings().config_dir / "profile.yaml")
    return _load_model(path, ProfileConfig)
