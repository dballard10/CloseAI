set shell := ["bash", "-cu"]

venv := ".venv"
python := ".venv/bin/python"
pip := ".venv/bin/pip"
backend_port := env_var_or_default("BACKEND_PORT", "8000")

default:
    @just --list --justfile backend.just

setup: env spacy-model

env:
    @if [ -f .env ]; then \
        echo ".env already exists"; \
    else \
        cp .env.example .env; \
        echo "Created .env from .env.example"; \
    fi
    @echo "For live OpenAI replies, set OPENAI_API_KEY in .env. For offline testing, set CLOSEAI_PROVIDER=echo."

install: venv
    {{pip}} install --upgrade pip
    {{pip}} install -r requirements.txt

dev: install
    #!/usr/bin/env bash
    set -euo pipefail
    port="{{backend_port}}"
    listeners="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [ -n "$listeners" ]; then
      echo "Stopping existing backend server on port $port."
      kill $listeners 2>/dev/null || true
      for _ in $(seq 1 30); do
        if ! lsof -ti tcp:"$port" >/dev/null 2>&1; then
          break
        fi
        sleep 0.2
      done
      listeners="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
      if [ -n "$listeners" ]; then
        echo "Force-stopping backend server on port $port."
        kill -9 $listeners 2>/dev/null || true
      fi
    fi
    exec {{python}} -m uvicorn app.server:app --reload --port "$port"

test: install
    {{python}} -m pytest tests

eval: install
    {{python}} eval/evaluate.py

spacy-model: install
    @{{python}} -c "import spacy; spacy.load('en_core_web_lg')" >/dev/null 2>&1 || {{python}} -m spacy download en_core_web_lg

venv:
    @test -d {{venv}} || python3 -m venv {{venv}}
