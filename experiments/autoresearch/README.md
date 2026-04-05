# Autoresearch Lane

This directory is reserved for offline experimentation only.

## Rules

- Do not import this lane into the production API runtime.
- Do not let experiments write directly into production scoring policies.
- Only run against frozen eval sets and persisted comparison artifacts.
- Valid experiment surfaces:
  - ranking weight search
  - prompt variant comparison
  - candidate heuristic comparison
  - subtitle packaging heuristics

## Current Status

- Not implemented yet.
- Production runtime remains `FastAPI + workers` only.
