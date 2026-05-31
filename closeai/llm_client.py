"""Client for the *closed-source* model — the untrusted party in the threat model.

By the time anything reaches here it has already been de-identified, so it is
safe to send to OpenAI / Anthropic / W&B Inference. Supported providers:

  - "openai"     OpenAI Chat Completions
  - "anthropic"  Anthropic Messages API
  - "wandb"      W&B Inference (OpenAI-compatible endpoint)
  - "ollama"     a local model via Ollama for no-egress demos
  - "echo"       offline stub for demos with no API key
"""

from __future__ import annotations

import os

from .observability import op


class ModelProviderError(RuntimeError):
    """A user-actionable failure from the configured model provider."""

    def __init__(self, provider: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.provider = provider
        self.message = message
        self.status_code = status_code


def provider_is_configured(provider: str) -> bool:
    """Return whether the provider has the local credentials it needs."""
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if provider == "wandb":
        return bool(os.getenv("WANDB_API_KEY"))
    return True


class ClosedModelClient:
    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        ollama_host: str = "http://localhost:11434",
    ):
        self.provider = provider
        self.model = model
        self.ollama_host = ollama_host.rstrip("/")
        self._resolved_ollama_model: str | None = None

    @op
    def complete(self, prompt: str, system: str | None = None) -> str:
        if self.provider == "openai":
            return self._openai(prompt, system)
        if self.provider == "wandb":
            return self._openai(prompt, system, wandb=True)
        if self.provider == "anthropic":
            return self._anthropic(prompt, system)
        if self.provider == "ollama":
            return self._ollama(prompt, system)
        return self._echo(prompt)

    def _openai(self, prompt: str, system: str | None, wandb: bool = False) -> str:
        if wandb:
            if not os.getenv("WANDB_API_KEY"):
                raise ModelProviderError(
                    "wandb",
                    "WANDB_API_KEY is required to use W&B Inference.",
                    status_code=400,
                )
            # NB: use a dedicated var, NOT WANDB_BASE_URL — that one is reserved by
            # wandb/weave to reach the W&B *platform* and would break tracing.
        else:
            if not os.getenv("OPENAI_API_KEY"):
                raise ModelProviderError(
                    "openai",
                    "OPENAI_API_KEY is required to use OpenAI. Select echo for an offline demo.",
                    status_code=400,
                )

        from openai import OpenAI

        if wandb:
            client = OpenAI(
                base_url=os.getenv("WANDB_INFERENCE_BASE_URL", "https://api.inference.wandb.ai/v1"),
                api_key=os.getenv("WANDB_API_KEY"),
            )
        else:
            client = OpenAI()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            resp = client.chat.completions.create(model=self.model, messages=messages)
        except Exception as exc:
            provider = "wandb" if wandb else "openai"
            raise ModelProviderError(
                provider,
                f"{provider.upper()} request failed: {exc}",
            ) from exc
        return resp.choices[0].message.content or ""

    def _anthropic(self, prompt: str, system: str | None) -> str:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise ModelProviderError(
                "anthropic",
                "ANTHROPIC_API_KEY is required to use Anthropic.",
                status_code=400,
            )
        import anthropic

        client = anthropic.Anthropic()
        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system or "You are a helpful assistant.",
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise ModelProviderError(
                "anthropic",
                f"Anthropic request failed: {exc}",
            ) from exc
        return "".join(block.text for block in resp.content if block.type == "text")

    def _ollama(self, prompt: str, system: str | None) -> str:
        import requests

        model = self._resolve_ollama_model()
        if not model:
            return (
                f"[CloseAI] Could not reach Ollama at {self.ollama_host}. "
                "Start it with `ollama serve` and pull a model (e.g. `ollama pull llama3.2`)."
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            resp = requests.post(
                f"{self.ollama_host}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
                timeout=180,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
        except Exception as exc:  # pragma: no cover - network/Ollama down
            return f"[CloseAI] Ollama request failed ({exc})."

    def _resolve_ollama_model(self) -> str | None:
        """Use the configured model if installed, else fall back to an installed
        one. Cached so we only hit /api/tags once."""
        if self._resolved_ollama_model is not None:
            return self._resolved_ollama_model or None
        import requests

        try:
            resp = requests.get(f"{self.ollama_host}/api/tags", timeout=10)
            resp.raise_for_status()
            available = [m["name"] for m in resp.json().get("models", [])]
        except Exception as exc:
            print(f"[ClosedModelClient] Ollama unreachable ({exc}).")
            self._resolved_ollama_model = ""
            return None
        if not available:
            self._resolved_ollama_model = ""
            return None

        chosen = self.model if self.model in available else None
        if chosen is None:
            base = self.model.split(":")[0]
            chosen = next((n for n in available if n.split(":")[0] == base), None)
        if chosen is None:
            chosen = available[0]
            print(
                f"[ClosedModelClient] model '{self.model}' not in Ollama; "
                f"using '{chosen}' (installed: {', '.join(available)})."
            )
        self._resolved_ollama_model = chosen
        return chosen

    @staticmethod
    def _echo(prompt: str) -> str:
        return (
            "[echo provider — no live model called]\n"
            "I received your de-identified message:\n\n"
            f"{prompt}"
        )
