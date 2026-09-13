# VALIDATION INSTRUCTIONS

## Overview

The validation flow now has three layers:

1. `QUICK_VALIDATION_CHECK.py`
   Confirms that the critical code paths, imports, and project entrypoints still exist.
2. `VALIDATION_LIVE_TEST.py`
   Captures the current assistant readiness surfaces and writes a guided report for manual desktop validation.
3. `VALIDATION_P1_LIVE.py`
   Captures the P1 readiness surface for `investigar`, `youtube`, `word` and mouse workflow. By default it is a safe snapshot. With `--execute-live`, it runs one real attempt per target.

This is intentional. The repo does not claim full end-to-end desktop automation for every validation step by itself.

---

## Step 1: Quick Integrity Check

Run either:

```bash
cd c:\Users\Monitor\Desktop\proyectos\Asistente
py QUICK_VALIDATION_CHECK.py
```

or:

```bash
QUICK_CHECK.bat
```

Expected result:

```text
RAPHEL QUICK VALIDATION CHECK
[OK] Core modules loaded successfully
...
Total: 3/3 checks passed
```

If this step fails, stop here and review the reported import or source-inspection error before trying guided validation.

---

## Step 2: Prepare the Desktop for Guided Validation

Before running `RUN_VALIDATION.bat` or `VALIDATION_LIVE_TEST.py`, prepare a real desktop state:

1. Open Brave, Chrome, or the browser you want to validate.
2. Leave a Google results page or a starting browser window visible.
3. Open YouTube in another tab if you want to validate transcript or visible-text capture.
4. Open Word or the target editor if you want to validate focus and writing behavior.

Recommended window layout:

- Browser visible
- YouTube accessible
- Editor visible
- No unexpected modal or file dialog already open

---

## Step 3: Run Guided Validation

Run either:

```bash
cd c:\Users\Monitor\Desktop\proyectos\Asistente
py VALIDATION_LIVE_TEST.py
```

or:

```bash
RUN_VALIDATION.bat
```

What this runner actually does:

- Loads `RaphelAssistant`
- Captures `learning-status`
- Captures `skill-status investigar`
- Captures `skill-status youtube`
- Writes a guided JSON report to `logs/validation_results.json`
- Prints a manual checklist for the live desktop checks

What it does **not** claim to do:

- It does not guarantee a full browser journey by itself
- It does not claim a complete 5-test automated desktop suite
- It does not replace real manual observation of focus, modals, and source transitions

---

## Step 3b: Run P1 Validation

Safe snapshot mode:

```bash
cd c:\Users\Monitor\Desktop\proyectos\Asistente
py VALIDATION_P1_LIVE.py
```

or:

```bash
RUN_P1_VALIDATION.bat
```

Real-attempt mode, only after preparing the desktop:

```bash
py VALIDATION_P1_LIVE.py --execute-live
```

This writes:

```text
c:\Users\Monitor\Desktop\proyectos\Asistente\logs\p1_validation_results.json
```

It also exists as assistant commands:

```text
doctor
p1-validation
p1-validation --execute-live
```

---

## Step 4: Review the Report

The report is written to:

```text
c:\Users\Monitor\Desktop\proyectos\Asistente\logs\validation_results.json
```

Current structure:

```json
{
  "generated_at": "2026-05-19T14:05:00",
  "project_root": "c:\\Users\\Monitor\\Desktop\\proyectos\\Asistente",
  "mode": "guided_live_validation",
  "checks": {
    "docs_index_present": true,
    "quick_check_present": true,
    "run_validation_bat_present": true
  },
  "snapshots": {
    "learning_status": "...",
    "research_status": "...",
    "youtube_status": "..."
  },
  "manual_checklist": [
    "Abrir Brave o Chrome y confirmar que la busqueda real sigue saliendo de Google a una fuente valida.",
    "Abrir YouTube y confirmar que transcript o texto visible se pueden capturar sin caer en Ctrl+A ciego.",
    "Abrir Word o el editor objetivo y verificar foco correcto antes de escribir o releer."
  ]
}
```

---

## Manual Checklist

Mark each item after you verify it on the real desktop:

```text
QUICK CHECK
  [ ] QUICK_CHECK.bat or py QUICK_VALIDATION_CHECK.py finished without crashes
  [ ] 3/3 quick checks passed

GUIDED VALIDATION
  [ ] VALIDATION_LIVE_TEST.py or RUN_VALIDATION.bat finished without crashes
  [ ] logs/validation_results.json was created
  [ ] learning-status snapshot looks current
  [ ] skill-status investigar reflects the current research bottleneck honestly
  [ ] skill-status youtube reflects transcript/text evidence honestly

REAL DESKTOP CHECKS
  [ ] Google results can transition to a real source instead of staying in SERP
  [ ] YouTube can use transcript or visible text without blind Ctrl+A
  [ ] The target editor keeps correct focus before typing
  [ ] Unexpected modals or file dialogs are detected instead of counted as success
```

---

## Failure Guide

### Quick check fails

Typical causes:

- Broken import path
- Renamed method without updating the check
- Missing root files such as `pyproject.toml` or `docs/README.md`

Action:

1. Read the failing section name.
2. Fix the missing import, method, or file.
3. Re-run `py QUICK_VALIDATION_CHECK.py`.

### Guided validation fails

Typical causes:

- `RaphelAssistant` fails during startup
- A runtime dependency is missing
- A command like `learning-status` or `skill-status investigar` raises an exception

Action:

1. Read the exact exception printed by the runner.
2. Fix the runtime issue.
3. Re-run `py VALIDATION_LIVE_TEST.py`.

### Guided report passes but desktop behavior is still bad

This means the snapshots are healthy enough to load, but the real workflow is still failing.

Action:

1. Reproduce the problem on the desktop.
2. Note whether the failure is:
   - still on Google results
   - help/sidebar detour
   - modal or file dialog
   - blocked page
   - relevant page with poor query alignment
3. Compare that behavior with `skill-status investigar` and `learning-status`.

---

## Truthfulness Standard

Validation success means verified evidence, not just an action being attempted.

- A click is not success.
- A page open is not success.
- A useful source transition with readable evidence is success.
- A transcript or visible text capture with alignment is success.
- Correct focus before typing is success.

---

## Related Files

- `QUICK_VALIDATION_CHECK.py`
- `VALIDATION_LIVE_TEST.py`
- `RUN_VALIDATION.bat`
- `QUICK_CHECK.bat`
- `docs/validation/FIXES_APPLIED.md`
- `docs/validation/VALIDATION_STATUS.md`
