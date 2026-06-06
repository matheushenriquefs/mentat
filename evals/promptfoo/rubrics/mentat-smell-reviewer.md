# Rubric: mentat-smell-reviewer

## Expected behavior

### long-method.diff
- MUST flag `long-method` for `process_everything` (35+ lines).
- MUST suggest Extract Method or equivalent.
- MUST NOT veto or block.
- Output under `smell_findings[]` header.

### feature-envy.diff
- MUST flag `feature-envy` for `Reporter.format_invoice` accessing order internals excessively.
- MUST suggest Move Method.
- MUST NOT veto or block.

### clean.diff
- MUST output empty `smell_findings[]` or omit findings section.
- MUST NOT flag false positives on a 5-line utility function.

## Format assertions (all fixtures)
- Output starts with or contains `smell_findings[]:` header.
- One finding per line: `path:line: <smell>. <fix>.`
- No prose paragraphs. No scores. No gate verdict.
