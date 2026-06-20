<!-- Example throughline card for a real refactor task. Copy to .throughline.md and edit. -->

# THROUGHLINE

meta:
  task_id: calc-to-class
  created: 2026-06-20
  updated: 2026-06-20 16:10
  size_budget_bytes: 8000

## === OBJECTIVE LOCK (verbatim) ===
OBJECTIVE: Refactor calc.py from standalone functions into a Calculator class with
add/sub/mul/div methods, keeping the existing CLI behavior identical.
TASK TYPE: refactor

## === OUT OF SCOPE ===
- Adding new math operations
- Changing the CLI argument format

## === PROGRESS CHECKLIST ===
- [x] Read calc.py and map current functions
- [x] Introduce Calculator class skeleton
- [~] Move add/sub into methods, keep functions as thin wrappers
- [ ] Move mul/div into methods
- [ ] Point CLI at the class and delete wrappers
- [ ] Run tests, confirm CLI output unchanged

## === NEXT ACTION ===
Move mul/div into Calculator methods, mirroring the add/sub pattern already in place.

## === DECISIONS (bounded, last 10) ===
- 2026-06-20 | Keep function wrappers until CLI is switched | avoids a big-bang break mid-refactor
