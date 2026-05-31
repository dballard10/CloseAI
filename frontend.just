set shell := ["bash", "-cu"]

default:
    @just --list --justfile frontend.just

setup: install

install: pnpm
    pnpm install

dev: pnpm
    pnpm dev

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
