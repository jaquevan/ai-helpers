---
id: table-pagination
title: Example fixture pagination convention
category: tables
automatable: true
automation_result: candidate
severity: error
---

## Rule

Review table pages for the fixture's pagination convention; a table match alone
does not prove a missing paginator.

## Automated Checks

```bash
grep -rl '<Pagination' --include='*.tsx' src/
```
