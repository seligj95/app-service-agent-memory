from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

from openai import AsyncAzureOpenAI


class EmbeddingService(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class DeterministicEmbeddingService:
    def __init__(self, dimensions: int = 1536) -> None:
        self._dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude:
            return [value / magnitude for value in vector]
        return vector


class AzureOpenAIEmbeddingService:
    def __init__(self, client: AsyncAzureOpenAI, deployment: str, dimensions: int) -> None:
        self._client = client
        self._deployment = deployment
        self._dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._deployment,
            input=text,
            dimensions=self._dimensions,
        )
        return response.data[0].embedding
