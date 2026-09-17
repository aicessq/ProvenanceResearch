# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with documentation in this repository.

- Follow the repository-wide instructions in `../CLAUDE.md`.
- `文档2.MD` is the authoritative executable specification; use it to resolve behavior and phase-boundary questions.
- The implementation is currently through Phase 10. Do not use older “pre-implementation” or Phase 0 assumptions.
- Keep architecture, startup, and verification documents aligned with behavior actually observed in code and tests.
- Never read credentials from tracked documentation files. Runtime credentials belong in the ignored `.env` file and must be loaded through `backend/app/config.py`.
