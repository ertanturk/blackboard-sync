---

# 1. PRIMARY OBJECTIVE

Your goal is NOT to write code.

Your goal is to:

- Understand the problem.
- Understand the architecture.
- Produce the smallest correct change.
- Preserve existing behavior.
- Verify results before responding.

Correctness > Speed

Simplicity > Cleverness

Architecture > Personal Preference

Evidence > Assumption

---

# 2. READ BEFORE WRITE

Before modifying any code:

1. Read the entire target file.
2. Read all directly related files.
3. Understand the call flow.
4. Understand ownership of responsibilities.
5. Identify side effects.
6. Identify concurrency implications.
7. Identify performance implications.

Never patch code based on partial context.

Never modify code you do not understand.

If understanding is incomplete:

STOP.

Ask questions.

---

# 3. ARCHITECTURE FIRST

Before implementing:

Read ARCHITECTURE.md.

Architecture documentation is the source of truth.

If implementation and architecture disagree:

Do not silently choose one.

Report the conflict.

Request clarification if necessary.

---

# 4. ARCHITECTURE PRESERVATION

Preserve architecture unless explicitly instructed otherwise.

Do not introduce:

- service layers
- manager layers
- factories
- wrappers
- adapters
- interfaces
- abstractions

unless the task explicitly requires them.

A working architecture is more valuable than a clever implementation.

---

# 5. SEPARATION OF CONCERNS

Never mix responsibilities.

Examples:

BAD

Downloader parses HTML.

GOOD

Crawler parses HTML.

Downloader downloads files.

---

BAD

Storage layer performs SQL parsing.

GOOD

SQL layer parses SQL.

Storage layer manages storage.

---

Every module should have one primary responsibility.

---

# 6. UNDERSTAND THE REQUEST

Before coding identify:

- What is requested?
- What is not requested?
- Which behavior must remain unchanged?
- Which files are affected?
- Which tests are affected?

Never expand scope without permission.

---

# 7. ASSUMPTION MANAGEMENT

Never hide assumptions.

Always explicitly state:

## Assumptions

Example:

- Router owns dispatch logic.
- TableHandler remains unchanged.
- Existing locking behavior must be preserved.

If assumptions are critical:

Ask for clarification.

---

# 8. SUCCESS CRITERIA

Convert requests into verifiable goals.

Example:

Goal 1:
Fix router bottleneck.

Verify:
Benchmark improves.

Goal 2:
Preserve behavior.

Verify:
Existing tests pass.

Goal 3:
Preserve architecture.

Verify:
No responsibility leakage.

Never use:

"It should work."

Use:

"I verified it by..."

---

# 9. SIMPLICITY FIRST

Implement the smallest correct solution.

Avoid:

- speculative features
- future-proofing
- unnecessary abstractions
- generic frameworks
- premature optimization

If 50 lines solve the problem:

Do not write 200.

---

# 10. NO SILENT REFACTORS

If the task is:

Fix X

Then fix X.

Do not:

- rename symbols
- move files
- rewrite unrelated logic
- reformat unrelated code
- change APIs
- redesign architecture

unless explicitly required.

Every changed line must directly support the requested task.

---

# 11. SURGICAL CHANGES

Touch only what is necessary.

When editing existing code:

- Match existing style.
- Preserve behavior.
- Avoid collateral modifications.

If unrelated issues are discovered:

Mention them.

Do not fix them without permission.

---

# 12. PYTHON STANDARDS

Minimum Python Version:

Python 3.14

Mandatory:

- Type hints
- Google-style docstrings
- Ruff compliance
- ty compliance

Use:

```python
list[str]
dict[str, int]
tuple[int, ...]
```

Avoid legacy typing syntax.

---

# 13. DOCUMENTATION RULES

Every module, class, method and function must contain docstrings.

Required sections when applicable:

- Args
- Returns
- Raises
- Notes
- Examples

Code should explain intent.

Docstrings should explain behavior.

---

# 14. LOGGING RULES

Use logging.

Never use print().

Logs must:

- be written in English
- contain context
- contain identifiers
- contain failure reasons

Bad:

```python
print("error")
```

Good:

```python
logger.error(
    "Failed to flush page %s due to checksum mismatch.",
    page_id,
)
```

---

# 15. ERROR HANDLING

Use specific exceptions.

Provide context.

Chain exceptions.

Example:

```python
raise ValueError(
    f"Invalid page size {page_size}."
) from exc
```

Never use:

```python
except:
```

---

# 16. PERFORMANCE RULES

Do not optimize blindly.

Identify:

- CPU bottlenecks
- Memory bottlenecks
- Lock contention
- Disk I/O bottlenecks
- Network bottlenecks

Measure before optimizing.

Avoid:

- repeated serialization
- repeated disk access
- unnecessary copies
- unnecessary locking

---

# 17. CONCURRENCY RULES

Before introducing concurrency:

Analyze:

- race conditions
- deadlocks
- lock contention
- shared mutable state

Required:

- thread safety
- deterministic behavior
- cleanup guarantees

Concurrency must solve a measured problem.

Not a hypothetical one.

---

# 18. TESTING REQUIREMENTS

New features require tests.

Bug fixes require reproduction tests.

Required verification:

```bash
pytest
```

When applicable:

```bash
ruff check .
```

```bash
ty check
```

Never claim success without verification.

---

# 19. SECURITY RULES

Never:

- hardcode credentials
- hardcode secrets
- disable validation
- bypass authentication

Validate all external input.

Fail safely.

---

# 20. SELF-REVIEW LOOP

Before returning code ask:

1. Did I understand the problem?
2. Did I read enough code?
3. Did I preserve architecture?
4. Did I change more than required?
5. Did I preserve existing behavior?
6. Can I prove the fix works?
7. What could break?
8. Is there a simpler solution?

If any answer is uncertain:

Continue analysis.

Do not return code yet.

---

# 21. REQUIRED OUTPUT FORMAT

Every coding response must contain:

## Assumptions

Explicit assumptions.

## Plan

Implementation strategy.

## Changes

What changed.

## Verification

How correctness was verified.

## Risks

Potential concerns or unknowns.

## Confidence

High
Medium
Low

Definitions:

High:
Verified by code inspection and tests.

Medium:
Supported by code inspection but not fully tested.

Low:
Relies on assumptions or missing context.

---

# 22. FINAL CHECKLIST

Before responding:

- [ ] Request understood
- [ ] Relevant files read
- [ ] Architecture analyzed
- [ ] Assumptions documented
- [ ] Success criteria defined
- [ ] Minimal implementation
- [ ] No unnecessary abstractions
- [ ] No silent refactors
- [ ] Separation of concerns preserved
- [ ] Type hints complete
- [ ] Docstrings complete
- [ ] Logging reviewed
- [ ] Error handling reviewed
- [ ] Performance impact reviewed
- [ ] Concurrency impact reviewed
- [ ] Edge cases reviewed
- [ ] Tests added if required
- [ ] Verification completed
- [ ] Self-review completed

If any item remains unchecked:

Do not return code.
