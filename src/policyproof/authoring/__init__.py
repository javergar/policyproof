"""Authoring a policy from a markdown document: extraction, problems in plain words, and checked proposals.

The pure modules (`document`, `plain`, `examples`, `merge`) import only the core and guards; `ports` and `propose` need
no model SDK; only `authoring.llm` calls models. See `docs/specs/2026-10-24-studio-design.md`.
"""
