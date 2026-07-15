from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_mode: Literal["fake", "azure"] = "fake"
    credential_mode: Literal["azure-cli", "managed-identity"] = "azure-cli"
    app_name: str = "Persistent Agent Memory"

    history_ttl_seconds: int = Field(default=604_800, ge=60, le=2_592_000)
    history_max_messages: int = Field(default=40, ge=2, le=200)
    recall_limit: int = Field(default=5, ge=1, le=10)
    memory_dimensions: int = Field(default=1536, ge=1, le=1536)
    api_requests_per_minute: int = Field(default=120, ge=1, le=10_000)

    azure_openai_endpoint: str | None = None
    azure_openai_chat_deployment: str = "gpt-5-mini"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    azure_openai_api_version: str = "preview"
    azure_openai_embedding_api_version: str = "2024-10-21"

    cosmos_endpoint: str | None = None
    cosmos_database: str = "agentmemory"
    cosmos_container: str = "memories"

    redis_host: str | None = None
    redis_port: int = Field(default=10000, ge=1, le=65535)
    redis_username: str | None = None

    @model_validator(mode="after")
    def validate_azure_configuration(self) -> Self:
        if self.app_mode == "azure":
            required = {
                "AZURE_OPENAI_ENDPOINT": self.azure_openai_endpoint,
                "COSMOS_ENDPOINT": self.cosmos_endpoint,
                "REDIS_HOST": self.redis_host,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"Azure mode requires: {', '.join(missing)}")
            if self.credential_mode == "azure-cli" and not self.redis_username:
                raise ValueError("Azure CLI Redis authentication requires REDIS_USERNAME")
            if self.memory_dimensions != 1536:
                raise ValueError("Azure mode requires 1,536-dimensional embeddings")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
