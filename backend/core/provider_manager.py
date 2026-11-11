import os
import json
import logging
import httpx
from typing import Dict, Any, List, Optional, AsyncIterator

logger = logging.getLogger("kela.providers")

class BaseInferenceProvider:
    """Abstract interface defining required capabilities for model inference providers."""
    name: str = "base"

    async def list_models(self) -> List[str]:
        raise NotImplementedError

    async def health_check(self) -> Dict[str, Any]:
        raise NotImplementedError

    async def generate_chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        raise NotImplementedError

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        raise NotImplementedError


class OllamaProvider(BaseInferenceProvider):
    """Local offline inference provider connecting to local Ollama daemon."""
    name: str = "ollama"

    def __init__(self, base_url: Optional[str] = None, default_model: Optional[str] = None):
        self.base_url = (base_url or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.default_model = default_model or os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
        self.timeout = httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=10.0)

    async def health_check(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    models = [m.get("name", "") for m in res.json().get("models", [])]
                    installed = any(self.default_model in m for m in models)
                    return {
                        "provider": self.name,
                        "available": True,
                        "base_url": self.base_url,
                        "models": models,
                        "active_model": self.default_model,
                        "model_installed": installed,
                    }
        except Exception as e:
            logger.debug("Ollama health probe error: %s", e)
            return {
                "provider": self.name,
                "available": False,
                "base_url": self.base_url,
                "error": f"Ollama unreachable at {self.base_url}: {str(e)}",
                "models": [],
                "active_model": self.default_model,
                "model_installed": False,
            }
        return {
            "provider": self.name,
            "available": False,
            "base_url": self.base_url,
            "error": "Ollama returned non-200 status",
            "models": [],
            "active_model": self.default_model,
            "model_installed": False,
        }

    async def list_models(self) -> List[str]:
        health = await self.health_check()
        return health.get("models", [])

    async def generate_chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        target_model = model or self.default_model
        payload = {
            "model": target_model,
            "messages": messages,
            "stream": False,
            "options": options or {"temperature": 0.4, "num_predict": 2048},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "").strip()

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        target_model = model or self.default_model
        payload = {
            "model": target_model,
            "messages": messages,
            "stream": True,
            "options": options or {"num_ctx": 8192, "num_predict": 2048},
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            yield {"error": "Invalid JSON chunk received from Ollama"}
                            return

                        if event.get("error"):
                            yield {"error": str(event["error"])}
                            return

                        content = event.get("message", {}).get("content", "")
                        if content:
                            yield {"token": content}

                        if event.get("done"):
                            yield {"done": True, "total_duration": event.get("total_duration")}
        except httpx.ConnectError:
            yield {
                "error": f"Cannot connect to Ollama at {self.base_url}. Ensure 'ollama serve' is running."
            }
        except httpx.TimeoutException:
            yield {"error": "Inference request timed out after 300s."}
        except Exception as e:
            yield {"error": f"Ollama streaming failure: {str(e)}"}


class CloudProviderAdapter(BaseInferenceProvider):
    """
    Adapter interface for cloud inference providers (OpenAI / Anthropic / Gemini).
    Ensures credentials remain exclusively server-side and never leak to the client.
    """
    name: str = "cloud"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: str = "gpt-4o-mini",
    ):
        self.api_key = api_key or os.environ.get("KELA_CLOUD_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.base_url = (base_url or os.environ.get("KELA_CLOUD_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.default_model = default_model
        self.timeout = httpx.Timeout(connect=5.0, read=120.0, write=15.0, pool=5.0)

    async def health_check(self) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "provider": self.name,
                "available": False,
                "configured": False,
                "reason": "KELA_CLOUD_API_KEY not configured. Set environment variable to enable cloud inference.",
                "models": [],
            }
        return {
            "provider": self.name,
            "available": True,
            "configured": True,
            "base_url": self.base_url,
            "models": [self.default_model],
        }

    async def list_models(self) -> List[str]:
        if not self.api_key:
            return []
        return [self.default_model]

    async def generate_chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("Cloud provider is not configured. Set KELA_CLOUD_API_KEY.")
        target_model = model or self.default_model
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": target_model, "messages": messages, "stream": False}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        if not self.api_key:
            yield {
                "error": "Cloud provider is not configured. Set KELA_CLOUD_API_KEY in environment to enable cloud fallback."
            }
            return

        target_model = model or self.default_model
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": target_model, "messages": messages, "stream": True}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            yield {"done": True}
                            return
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {}).get("content", "")
                            if delta:
                                yield {"token": delta}
                        except Exception:
                            continue
        except Exception as e:
            yield {"error": f"Cloud inference failure: {str(e)}"}


class ProviderManager:
    """Coordinates available model providers, active model resolution, and failover routing."""

    def __init__(self):
        self._providers: Dict[str, BaseInferenceProvider] = {
            "ollama": OllamaProvider(),
            "cloud": CloudProviderAdapter(),
        }
        self.active_provider_name = os.environ.get("KELA_ACTIVE_PROVIDER", "ollama")

    def register_provider(self, name: str, provider: BaseInferenceProvider):
        self._providers[name] = provider

    def get_provider(self, name: Optional[str] = None) -> BaseInferenceProvider:
        key = name or self.active_provider_name
        if key not in self._providers:
            raise KeyError(f"Provider '{key}' is not registered. Available: {list(self._providers.keys())}")
        return self._providers[key]

    def get_active_provider(self) -> BaseInferenceProvider:
        return self.get_provider(self.active_provider_name)

    async def get_all_providers_status(self) -> Dict[str, Any]:
        statuses = {}
        for name, prov in self._providers.items():
            statuses[name] = await prov.health_check()
        return {
            "active_provider": self.active_provider_name,
            "providers": statuses,
        }

    async def execute_with_fallback(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Attempts execution on active provider. If active provider encounters a connection error
        and a healthy fallback is available, seamlessly falls back while reporting honest diagnostics.
        """
        primary = self.get_active_provider()
        has_error = False
        error_msg = ""

        async for chunk in primary.stream_chat(messages, model, options):
            if "error" in chunk and "Cannot connect" in chunk["error"]:
                has_error = True
                error_msg = chunk["error"]
                break
            yield chunk

        if has_error:
            # Check if cloud fallback is available
            fallback = self.get_provider("cloud")
            fb_health = await fallback.health_check()
            if fb_health.get("available"):
                yield {"step": "Local provider unavailable; falling back to Cloud provider..."}
                async for fb_chunk in fallback.stream_chat(messages, model, options):
                    yield fb_chunk
            else:
                yield {"error": error_msg}


provider_manager = ProviderManager()
