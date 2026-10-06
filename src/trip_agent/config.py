"""Explicit model profiles; persisted settings never contain credentials."""

import importlib.util
import os
import re
import tomllib
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AppError(Exception):
    """An actionable error suitable for display without a traceback."""


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["openai", "anthropic", "bedrock", "openrouter"]
    model_id: str = Field(min_length=1)
    api_key_env: str | None = None
    region: str | None = None
    aws_profile: str | None = None
    max_model_calls: int = Field(default=12, ge=1, le=30)
    timeout_seconds: int = Field(default=60, ge=5, le=300)

    @field_validator("api_key_env")
    @classmethod
    def env_name(cls, value):
        if value is not None and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", value):
            raise ValueError("api_key_env must be an environment variable NAME, not a key")
        return value

    @field_validator("model_id")
    @classmethod
    def model_name(cls, value):
        if not value.strip() or value.startswith("<"):
            raise ValueError("Provide an actual model ID")
        return value

    @property
    def credential_env(self):
        return self.api_key_env or {
            "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
            "openrouter": "OPENROUTER_API_KEY", "bedrock": "AWS_BEARER_TOKEN_BEDROCK",
        }[self.provider]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_profile: str
    profiles: dict[str, Profile]

    def select(self, name: str | None = None) -> tuple[str, Profile]:
        name = name or self.default_profile
        if name not in self.profiles:
            raise AppError(f"Unknown profile '{name}'. Available: {', '.join(self.profiles)}")
        return name, self.profiles[name]


def load_settings(path: Path) -> Settings:
    if not path.is_file():
        raise AppError(f"No configuration at {path}. Run: trip-agent config init")
    load_dotenv(path.parent / ".env", override=False)
    try:
        settings = Settings.model_validate(tomllib.loads(path.read_text()))
        settings.select()
        return settings
    except (ValueError, tomllib.TOMLDecodeError) as exc:
        raise AppError(f"Invalid configuration at {path}: {exc}") from exc


def initialize_config(path: Path, provider: str, model: str) -> None:
    if path.exists():
        raise AppError(f"Configuration already exists at {path}; edit it to add profiles.")
    profile = Profile(provider=provider, model_id=model)
    import json
    # JSON-quoted strings are also valid TOML basic strings.
    lines = [f'default_profile = "{provider}"', "", f"[profiles.{provider}]",
             f'provider = "{provider}"', f"model_id = {json.dumps(model)}"]
    if provider == "bedrock":
        lines += ['region = "us-west-2"', '# aws_profile = "default"']
    else:
        lines += [f'api_key_env = "{profile.credential_env}"']
    lines += ["max_model_calls = 12", "timeout_seconds = 60", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as file:
        file.write("\n".join(lines))


def check_profile(profile: Profile) -> list[str]:
    """Local check only; never contact a model or AWS metadata service."""
    module = {"openai": "openai", "openrouter": "openai", "anthropic": "anthropic", "bedrock": "boto3"}[profile.provider]
    problems = []
    if importlib.util.find_spec(module) is None:
        problems.append(f"Missing provider dependency. Install: pip install -e '.[{profile.provider}]'")
    if profile.provider != "bedrock" and not os.environ.get(profile.credential_env):
        problems.append(f"Set {profile.credential_env} in the environment or the configuration directory's .env file.")
    if profile.provider == "bedrock" and not profile.region:
        problems.append("Set region in the Bedrock profile.")
    return problems
