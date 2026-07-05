"""LLM response cache — identical (model, prompt, input) within the TTL is
served from disk instead of re-billed. Key covers the prompt file content,
so editing a prompt invalidates its cached responses automatically."""
import hashlib
import json

from ..data.base import DiskTTLCache

TTL_LLM = 24 * 3600


def response_key(model: str, system_prompt: str, payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    material = f"{model}\x00{system_prompt}\x00{canonical}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class LLMCache:
    def __init__(self, disk_cache: DiskTTLCache):
        self._cache = disk_cache

    def get(self, key: str) -> dict | None:
        return self._cache.get("llm", key)

    def put(self, key: str, result: dict) -> None:
        self._cache.put("llm", key, result, TTL_LLM)
