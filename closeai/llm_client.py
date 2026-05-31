"""Client for the *closed-source* model — the untrusted party in the threat model.

By the time anything reaches here it has already been de-identified, so it is
safe to send to OpenAI / Anthropic / W&B Inference. Supported providers:

  - "openai"    OpenAI Chat Completions (also works for W&B Inference via base_url)
  - "anthropic" Anthropic Messages API
  - "wandb"     W&B Inference (OpenAI-compatible endpoint)
  - "ollama"    a local model via Ollama — handy for testing the full
                de-identify -> answer -> re-identify round-trip with no API key.
  - "echo"      offline stub for demos with no API key — echoes the masked text
                so you can still see the full mask -> reidentify round-trip.
"""

from __future__ import annotations

import os

from .observability import log_llm_call, op


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
        from openai import OpenAI

        provider = "wandb" if wandb else "openai"
        endpoint = os.getenv("WANDB_INFERENCE_BASE_URL", "https://api.inference.wandb.ai/v1") if wandb else None
        if wandb:
            # NB: use a dedicated var, NOT WANDB_BASE_URL — that one is reserved by
            # wandb/weave to reach the W&B *platform* and would break tracing.
            client = OpenAI(
                base_url=endpoint,
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
            content = resp.choices[0].message.content or ""
            log_llm_call(
                provider=provider,
                model=self.model,
                stage="legacy.closed_model",
                system=system or "",
                user=prompt,
                response=content,
                endpoint=endpoint,
            )
            return content
        except Exception as exc:
            log_llm_call(
                provider=provider,
                model=self.model,
                stage="legacy.closed_model",
                system=system or "",
                user=prompt,
                error=str(exc),
                endpoint=endpoint,
            )
            raise

    def _anthropic(self, prompt: str, system: str | None) -> str:
        import anthropic

        client = anthropic.Anthropic()
        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system or "You are a helpful assistant.",
                messages=[{"role": "user", "content": prompt}],
            )
            content = "".join(block.text for block in resp.content if block.type == "text")
            log_llm_call(
                provider="anthropic",
                model=self.model,
                stage="legacy.closed_model",
                system=system or "You are a helpful assistant.",
                user=prompt,
                response=content,
            )
            return content
        except Exception as exc:
            log_llm_call(
                provider="anthropic",
                model=self.model,
                stage="legacy.closed_model",
                system=system or "You are a helpful assistant.",
                user=prompt,
                error=str(exc),
            )
            raise

    def _ollama(self, prompt: str, system: str | None) -> str:
        import requests

        model = self._resolve_ollama_model()
        if not model:
            log_llm_call(
                provider="ollama",
                model=self.model,
                stage="legacy.closed_model",
                system=system or "",
                user=prompt,
                error="no local model available",
                endpoint=self.ollama_host,
            )
            return "[ollama provider — no local model available]"
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
            content = resp.json().get("message", {}).get("content", "")
            log_llm_call(
                provider="ollama",
                model=model,
                stage="legacy.closed_model",
                system=system or "",
                user=prompt,
                response=content,
                endpoint=self.ollama_host,
            )
            return content
        except Exception as exc:
            log_llm_call(
                provider="ollama",
                model=model,
                stage="legacy.closed_model",
                system=system or "",
                user=prompt,
                error=str(exc),
                endpoint=self.ollama_host,
            )
            raise

    def _resolve_ollama_model(self) -> str | None:
        """Use the configured model if installed, else fall back to an installed
        one. The default ``CLOSEAI_MODEL`` (e.g. gpt-4o-mini) isn't an Ollama
        model, so this keeps the ollama provider working out of the box."""
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
