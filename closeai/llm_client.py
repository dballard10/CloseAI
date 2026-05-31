"""Client for the *closed-source* model — the untrusted party in the threat model.

By the time anything reaches here it has already been de-identified, so it is
safe to send out. This build targets a **local Ollama model only** — handy for
testing the full de-identify -> answer -> re-identify round-trip with no API
keys and nothing leaving the machine.

If the configured model isn't installed, it auto-falls back to one that is.
"""

from __future__ import annotations

from .observability import op


class ClosedModelClient:
    def __init__(self, model: str = "llama3.2", ollama_host: str = "http://localhost:11434"):
        self.model = model
        self.ollama_host = ollama_host.rstrip("/")
        self._resolved_model: str | None = None

    @op
    def complete(self, prompt: str, system: str | None = None) -> str:
        import requests

        model = self._resolve_model()
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

    def _resolve_model(self) -> str | None:
        """Use the configured model if installed, else fall back to an installed
        one. Cached so we only hit /api/tags once."""
        if self._resolved_model is not None:
            return self._resolved_model or None
        import requests

        try:
            resp = requests.get(f"{self.ollama_host}/api/tags", timeout=10)
            resp.raise_for_status()
            available = [m["name"] for m in resp.json().get("models", [])]
        except Exception as exc:
            print(f"[ClosedModelClient] Ollama unreachable ({exc}).")
            self._resolved_model = ""
            return None
        if not available:
            self._resolved_model = ""
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
        self._resolved_model = chosen
        return chosen
