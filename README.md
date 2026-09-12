# Kobald EvalKit

Standalone, open-source local AI evaluation toolkit. Repeatable behavioural
tests for local models, starting with Ollama. Not a universal intelligence
score.

- Python >= 3.10, stdlib-only runtime, pytest for development.
- Deterministic scoring where possible; unreliable judgement is explicitly
  flagged `needs_human` instead of guessed.

Status: v0.1 scaffold. Full docs land in M2/M3.