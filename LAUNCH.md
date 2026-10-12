# claimcheck — launch plan

## One-line pitch

> Your agent says "I deployed it." claimcheck checks whether it did.

## The problem, stated plainly

Agent systems in 2026 fail silently. Not by crashing — by *reporting success*.
A run writes a summary, the summary says the work is done, the work is not done,
and the pipeline marks the run green.

Existing tooling measures topology: how many jobs, how many skills, whether the
service is up. Nothing measures whether the agent's claims match its tool
results.

## Real finding from this machine

Transcript: `~/.hermes/sessions/20260520_085424_cfcd6681.jsonl`

Agent: *"Found it — I updated memory but never actually wrote the file."*

Tool results in the same transcript:

```json
{"success": false, "error": "Memory at 2,140/2,200 chars. Adding this entry (147 chars) would exceed the limit."}
{"success": false, "error": "No entry matched 'Trading: $3,010. Aggressive params May 17 ...'"}
```

Both memory writes failed. The agent reported success anyway. claimcheck flags
it as **contradicted**.

That is the whole product in one example.

## Target audience

1. **Agent fleet operators** — people running Hermes, OpenClaw, Claude Code, or
   LangGraph agents with cron jobs and multi-step pipelines. They already
   suspect their agents are lying to them.
2. **Teams shipping agent products** — anyone with an agent in a CI or
   production pipeline that needs a verification gate before a run counts as
   successful.
3. **Compliance / audit** — "prove the agent actually did what it claims" is a
   procurement requirement in regulated environments.

## Where to launch

- r/openclaw, r/LocalLLaMA, Hacker News, Lobsters
- The Hermes/OpenClaw skill directories
- Direct: post the real transcript finding. Concrete evidence beats a pitch.

Launch post skeleton:

> I built a CLI that reads an agent's transcript and checks every claim of
> completed action against the tool results that actually happened. On my own
> setup it found an agent that said "I updated memory" while both memory calls
> returned `success: false`. Nine ground-truth tests, CI green, MIT licensed.
> `pip install .` from source.

## Monetization

**Free:** local CLI, single transcript, all four statuses, gate exit codes.

**Pro ($19/mo):**
- Continuous monitoring across sessions, not one-off audits
- Alerting when an agent's overclaim rate trends upward
- Runtime gate that blocks a run from being marked successful
- Parser adapters for LangGraph, OpenAI Agents SDK, Claude Code transcripts
- Multi-agent fleet dashboards with per-agent claim profiles

**Enterprise:** audit-trail export, retention, SSO.

Honest estimate: this is a niche tool. Realistic ceiling for a solo builder in
this space is $1–5K MRR. It is not a rocket. It is a real tool for a real,
documented problem, and the second product in a portfolio that compounds
distribution.

## Status

- Public repo: https://github.com/Crow0077/claimcheck
- CI: green, Python 3.9–3.14
- Not on PyPI yet
- No billing implemented
