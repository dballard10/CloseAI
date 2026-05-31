set shell := ["bash", "-cu"]

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

dev:
    #!/usr/bin/env bash
    set -euo pipefail

    pids=()

    cleanup() {
      for pid in "${pids[@]:-}"; do
        if kill -0 "$pid" 2>/dev/null; then
          kill "$pid" 2>/dev/null || true
        fi
      done
    }

    trap cleanup EXIT INT TERM

    just --justfile backend.just dev &
    pids+=("$!")

    just --justfile frontend.just dev &
    pids+=("$!")

    while true; do
      for pid in "${pids[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
          wait "$pid"
          exit $?
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
