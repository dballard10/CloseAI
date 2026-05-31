set shell := ["bash", "-cu"]

frontend_port := env_var_or_default("FRONTEND_PORT", "5173")

default:
    @just --list --justfile frontend.just

setup: install

install: pnpm
    pnpm install

dev: install
    #!/usr/bin/env bash
    set -euo pipefail
    port="{{frontend_port}}"
    listeners="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [ -n "$listeners" ]; then
      echo "Stopping existing frontend dev server on port $port."
      kill $listeners 2>/dev/null || true
      for _ in $(seq 1 30); do
        if ! lsof -ti tcp:"$port" >/dev/null 2>&1; then
          break
        fi
        sleep 0.2
      done
      listeners="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
      if [ -n "$listeners" ]; then
        echo "Force-stopping frontend dev server on port $port."
        kill -9 $listeners 2>/dev/null || true
      fi
    fi
    exec pnpm exec vite --port "$port"

build: install
    pnpm build

preview: build
    pnpm preview

pnpm:
    @if command -v pnpm >/dev/null 2>&1; then \
        pnpm --version >/dev/null; \
    elif command -v corepack >/dev/null 2>&1; then \
        corepack enable pnpm; \
    else \
        echo "pnpm is required. Install Node.js with Corepack or install pnpm directly."; \
        exit 1; \
    fi
