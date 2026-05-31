# Concept Space Tensor Model

This document defines the staged, space-first learning model used by the API.

## Core Idea

A concept is represented as the composition of its states across spaces.

- Some concepts may exist in only one space.
- Others can span many spaces (semantic, goal, memory, attention, risk, arithmetic, calculus, curriculum, self).
- Learning is not flat: spaces are unlocked from foundation to abstraction.

## Representation

Treat a concept as a tensor-like structure:

- Axis X: concept identity
- Axis Y: space identity
- Axis Z: feature vector dimensions per space (embedding vector)
- Optional Axis T: time/update index for longitudinal learning

The runtime store persists this via per-concept, per-space vectors and computes inter-space differences.

## Space Progression

Recommended bootstrap order:

1. language_literacy
2. numeric_literacy
3. goal_and_risk_grounding
4. memory_and_attention_context
5. advanced_symbolic_reasoning

The order enforces prerequisite progression. Example:

- Arithmetic is blocked before digits/operators are learned.
- A device concept (for example TV) can be known without fully teaching EM theory.

## Answer Policy

The API applies a no-speculation policy for unknown concepts.

- Symbolic math intent: delegated to symbolic path (still gated by curriculum prerequisites).
- Non-symbolic query with no lexical tokens: no answer.
- Non-symbolic query with only unknown tokens: no answer.
- Non-symbolic query with at least one known token: answer from learned knowledge only.

Policy is returned in `semantic/search` and `semantic/recall` payloads.

## Reset + Rebootstrap

Use reset endpoint before training from scratch:

- `POST /learn/reset?confirm=true`
- `POST /learn/reset?confirm=true&include_archives=true`

Then execute bootstrap in order using curriculum/ingest actions.
