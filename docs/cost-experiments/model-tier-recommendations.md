# Model tier recommendations (CP4)

```bash
make run-model-experiments KEY=RHAISTRAT-1492 URL=http://localhost:9000
```

## Anthropic CLI results

| Phase | Opus (golden) | Sonnet-5 | Sonnet-4.6 | Haiku-4.5 | Decision |
|-------|---------------|----------|------------|-----------|----------|
| eval-extract | | | | | |
| eval-classify | | | | | |
| eval-journey | | | | | |
| eval-usability | | | | | |
| eval-fix | | | | | |

## Cursor Grok (quality only — no $ gate)

| Run | Model | vs Golden-A quality | Latency | Decision |
|-----|-------|---------------------|---------|----------|
| Orchestrator | cursor-grok-4.5-high | | | |
| Journey/usability | cursor-grok-4.6-xhigh | | | |
| Iterate probe | cursor-grok-4.6-xhigh | | | |

## Recommended default mix

Locked in `plugins/uxd-workshop/skills/uxd-prototype-evaluate/config/model-defaults.yaml`.
No model probes — input-diet experiments come later.

| Phase | Model | Tier |
|-------|-------|------|
| eval-extract | claude-haiku-4-5 | Haiku |
| eval-classify | claude-haiku-4-5 | Haiku |
| eval-journey | claude-sonnet-4-6 | Sonnet |
| eval-usability | claude-sonnet-4-6 | Sonnet |
| eval-consistency | claude-sonnet-4-6 | Sonnet |
| eval-report | claude-sonnet-4-6 | Sonnet |
| eval-fix | claude-opus-4-6 | Opus (iterate only) |

## Exceptions (you + Andy approved)

| Change | Quality trade-off | Approved |
|--------|-------------------|----------|
