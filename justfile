set shell := ["bash", "-cu"]

backend_port := env_var_or_default("BACKEND_PORT", "8000")
frontend_port := env_var_or_default("FRONTEND_PORT", "5173")

default:
    @just --list

setup: env
    just --justfile frontend.just setup
    just --justfile backend.just setup
    @echo "Setup complete. Run 'just dev' to start the app."

install:
    just --justfile frontend.just install
    just --justfile backend.just install

env:
    @if [ -f .env ]; then \
        echo ".env already exists"; \
    else \
        cp .env.example .env; \
        echo "Created .env from .env.example"; \
    fi
    @echo "For live OpenAI replies, set OPENAI_API_KEY in .env. For offline testing, set CLOSEAI_PROVIDER=echo."

dev:
    #!/usr/bin/env bash
    set -euo pipefail

    pids=()
    backend_port="{{backend_port}}"
    frontend_port="{{frontend_port}}"

    stop_port() {
      local label="$1"
      local port="$2"
      local listeners

      listeners="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
      if [ -z "$listeners" ]; then
        return 0
      fi

      echo "Stopping existing $label server on port $port."
      kill $listeners 2>/dev/null || true

      for _ in $(seq 1 30); do
        if ! lsof -ti tcp:"$port" >/dev/null 2>&1; then
          return 0
        fi
        sleep 0.2
      done

      listeners="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
      if [ -n "$listeners" ]; then
        echo "Force-stopping $label server on port $port."
        kill -9 $listeners 2>/dev/null || true
      fi
    }

    cleanup() {
      for pid in "${pids[@]:-}"; do
        if kill -0 "$pid" 2>/dev/null; then
          kill "$pid" 2>/dev/null || true
        fi
      done
      stop_port frontend "$frontend_port"
      stop_port backend "$backend_port"
    }

    trap cleanup EXIT INT TERM

    stop_port backend "$backend_port"
    stop_port frontend "$frontend_port"

    just env
    just --justfile backend.just install
    just --justfile frontend.just install

    just --justfile backend.just venv
    .venv/bin/python -m uvicorn app.server:app --reload --port "$backend_port" &
    pids+=("$!")

    if command -v pnpm >/dev/null 2>&1; then
      pnpm exec vite --port "$frontend_port" &
    elif command -v corepack >/dev/null 2>&1; then
      corepack enable pnpm
      pnpm exec vite --port "$frontend_port" &
    else
      echo "pnpm is required. Install Node.js with Corepack or install pnpm directly."
      exit 1
    fi
    pids+=("$!")

    echo "CloseAI backend:  http://localhost:$backend_port"
    echo "CloseAI frontend: http://localhost:$frontend_port"

    while true; do
      for pid in "${pids[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
          set +e
          wait "$pid"
          status="$?"
          set -e
          if [ "$status" -eq 130 ] || [ "$status" -eq 143 ]; then
            exit 0
          fi
          exit "$status"
        fi
      done
      sleep 1
    done

frontend:
    just --justfile frontend.just

frontend-dev:
    just --justfile frontend.just dev

frontend-build:
    just --justfile frontend.just build

backend:
    just --justfile backend.just

backend-dev:
    just --justfile backend.just dev

backend-test:
    just --justfile backend.just test

test: backend-test frontend-build

build: frontend-build
