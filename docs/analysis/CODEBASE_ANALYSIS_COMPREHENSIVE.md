# RAPHEL PROJECT - COMPREHENSIVE CODEBASE ANALYSIS

**Verified date:** 2026-05-18  
**Source of truth:** current repository state + current test suite  
**Current baseline:** the project is operationally substantial, but still needs live Windows validation to prove real learning quality

## Executive summary

The old broad claim that Raphel was mostly incomplete is no longer accurate. The repo already contains the main command, learning, research, organizer, and autonomous-learning plumbing. The real problem has shifted from "missing modules" to "runtime truthfulness": whether a live session actually opened the right window, captured useful text, stayed out of modals, and verified the outcome in the current session.

The current test suite passes with `180` tests via `py -m unittest discover tests`.

## What is confirmed to exist

- `core/assistant.py` contains working dispatch, confirmation, `learn_skill`, and `practice_skill` entrypoints.
- `core/memory.py` already exposes `get_preference`.
- `core/recovery_engine.py` is not a single hardcoded default selector.
- `core/autonomous_learning_system.py` is active code and performs research bootstrap plus direct fallback.
- `core/desktop_learning_organizer.py` already contains controlled-practice routes that avoid search-window contamination in the primary path.
- `core/learning_skill_engine.py` already contains dedicated cycles for keyboard, mouse, browser, research, YouTube, Word, Explorer, and generic application workflows.

## Repairs implemented in this pass

### 1. Research and browser evidence
- Research success is now tied to useful current-session capture rather than weak page transitions.
- Evidence is normalized around:
  - `source_kind`
  - `transcript_available`
  - `transcript_chars`
  - `visible_text_chars`
  - `page_usefulness_label`
  - `current_session_verified`
  - `verification_source`

### 2. YouTube
- YouTube now uses a local `transcript + OCR` path instead of relying only on generic visible-page OCR.
- OCR priority now covers transcript, captions, watch regions, metadata, and sidebar text.
- Level-3 YouTube workflow can now distinguish:
  - transcript-backed success
  - visible-text fallback success
  - insufficient capture failure

### 3. Word strict-real behavior
- Word now fails honestly on wrong focus, unexpected modals, empty capture, or text mismatch.
- Blocked Word profiles no longer recover because of soft history or stale success markers.
- Recovery now depends on fresh verified session evidence.

### 4. Autonomous learning asset quality
- Weak research assets are no longer promoted as strong knowledge assets.
- Asset promotion now requires real transcript/OCR or useful textual research substance.

## Real remaining blockers

### 1. Live browser reliability
- Google and YouTube can still break live flows through modals, anti-automation layouts, or poor OCR conditions.

### 2. Video understanding ceiling
- Raphel is now better at YouTube research.
- It still does not perform full audiovisual understanding from spoken audio, scene changes, and timeline context like a human would.

### 3. Live validation still required
- Passing tests is not enough to declare "real learning".
- The following still need end-to-end live Windows validation:
  - `aprende a investigar`
  - `aprende a usar youtube`
  - `aprende a usar word`
  - `desktop-practice-mouse-workflow`

## Bottom line

Raphel is no longer best described as a half-built shell. It is better described as a working learning/automation system whose biggest risks now live at the boundary between code and real Windows runtime behavior.
