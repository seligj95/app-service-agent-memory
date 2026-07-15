from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from azure.core.credentials import AccessToken, TokenCredential
from azure.identity import AzureCliCredential as SyncAzureCliCredential
from azure.identity.aio import (
    AzureCliCredential,
    ManagedIdentityCredential,
)
from azure.identity.aio import (
    get_bearer_token_provider as get_async_bearer_token_provider,
)
from redis.credentials import CredentialProvider
from redis_entraid.cred_provider import (
    ManagedIdentityType,
    create_from_managed_identity,
)

from app.config import Settings

REDIS_SCOPE = "https://redis.azure.com/.default"
REDIS_RESOURCE = "https://redis.azure.com/"
COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"


def create_async_credential(settings: Settings) -> AzureCliCredential | ManagedIdentityCredential:
    if settings.credential_mode == "managed-identity":
        return ManagedIdentityCredential()
    return AzureCliCredential()


def create_openai_token_provider(
    credential: AzureCliCredential | ManagedIdentityCredential,
) -> Callable[[], Awaitable[str]]:
    return get_async_bearer_token_provider(credential, COGNITIVE_SERVICES_SCOPE)


class AzureCliRedisCredentialProvider(CredentialProvider):
    def __init__(self, username: str, credential: TokenCredential | None = None) -> None:
        self._username = username
        self._credential = credential or SyncAzureCliCredential()

    def get_credentials(self) -> tuple[str, str]:
        token: AccessToken = self._credential.get_token(REDIS_SCOPE)
        return self._username, token.token

    def close(self) -> None:
        close = getattr(self._credential, "close", None)
        if close:
            close()


def create_redis_credential_provider(
    settings: Settings,
) -> CredentialProvider:
    if settings.credential_mode == "managed-identity":
        return cast(
            CredentialProvider,
            create_from_managed_identity(
                identity_type=ManagedIdentityType.SYSTEM_ASSIGNED,
                resource=REDIS_RESOURCE,
            ),
        )
    if not settings.redis_username:
        raise ValueError("REDIS_USERNAME is required for Azure CLI Redis authentication")
    return AzureCliRedisCredentialProvider(settings.redis_username)
