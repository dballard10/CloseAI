set shell := ["bash", "-cu"]

venv := ".venv"
python := ".venv/bin/python"
pip := ".venv/bin/pip"

default:
    @just --list --justfile backend.just

setup: spacy-model

install: venv
    {{pip}} install --upgrade pip
    {{pip}} install -r requirements.txt

dev: venv
    {{python}} -m uvicorn app.server:app --reload --port 8000

test: install
    {{python}} -m pytest tests

eval: install
    {{python}} eval/evaluate.py

spacy-model: install
    @{{python}} -c "import spacy; spacy.load('en_core_web_lg')" >/dev/null 2>&1 || {{python}} -m spacy download en_core_web_lg

venv:
    @test -d {{venv}} || python3 -m venv {{venv}}
