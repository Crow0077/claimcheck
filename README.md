# claimcheck

**Your agent said it did it. Did it?**

`claimcheck` reads an AI agent's session transcript and checks every claim of
completed action against the tool results that actually happened.

An agent writes: *"I updated memory but never actually wrote the file."*
Six tool calls later, the transcript shows:

```json
{"success": false, "error": "Memory at 2,140/2,200 chars. Adding this entry would exceed the limit."}
```

claimcheck flags that as **contradicted**. Not as a vibe. As a matched tool
result with a failure signature.

## Why this exists

Silent failure is the dominant failure mode of agent systems in 2026. Dashboards
report topology — how many jobs, how many skills, whether the service is up.
They do not report whether the agent's *claims* are true.

Academic work on agent verification ("a 'success' verdict is discarded unless at
least one of its quoted evidence lines is an actual tool result") describes the
problem. Nobody has shipped a tool that does it against a real transcript.

## Install

Not on PyPI yet. Install from source:

```bash
git clone https://github.com/Crow0077/claimcheck
cd claimcheck
pip install .
```

Or run it directly without installing:

```bash
python3 -m claimcheck.cli audit session.jsonl
```

## Usage

```bash
claimcheck audit session.jsonl              # human report
claimcheck audit session.jsonl --json       # machine-readable
claimcheck audit session.jsonl --md         # markdown table
claimcheck audit session.jsonl --strict     # evidence must precede the claim
claimcheck scan ~/.hermes/sessions          # every transcript in a directory
claimcheck explain session.jsonl --finding memory   # evidence trail for one claim
```

### As a gate

```bash
claimcheck audit session.jsonl --fail-on contradicted
```

Exits 1 if any claim is contradicted. Drop this into a CI step or an agent
pipeline so a run that overclaims cannot be marked successful.

### What `--strict` does

By default a claim counts as verified if *any* tool call in the transcript
matches it. In strict mode the evidence has to appear **before** the claim.
That is the difference between:

```
tool: deploy app -> exit 0
assistant: "I deployed the app."      # verified, strict
```

and

```
assistant: "I deployed the app."      # unverified, strict
tool: deploy app -> exit 0
```

The second is the dangerous shape: the agent asserted an outcome before doing
the work, and if the work then failed, the summary already shipped.

## Example output

```
SESSION  ~/.hermes/sessions/20260520_085424_cfcd6681.jsonl
  messages        138
  tool calls      68  (10 failed)
  claims          3
  overclaim rate  66.7%

RED   CONTRADICTED  (1)
    - "memory"
      Found it — I updated memory but never actually wrote the file. Fixing now.
      note: every matching tool call failed: success=false; success=false

CHK   PARTIAL  (2)
    - "positions.json"
      note: some matching calls failed: permission denied; 0 bytes
```

## How it decides

A claim is only verified if a tool call in the transcript matches it.

1. **Claim detection.** Outcome-asserting verbs with an agentive subject
   ("I created", "we deployed", "the script installed") plus result-state
   patterns ("tests passed", "service is running", "CI is green").
   Future tense ("I will create") and negation ("never wrote") are excluded.
   Analysis prose is excluded — "Configured dashboards are rare" is a
   description, not a claim that the agent configured anything.

2. **Evidence matching.** Weighted toward tool *arguments* (commands, paths,
   URLs) rather than result blobs. A web_search result that happens to contain
   the word "failed" is not evidence about the agent's action.

3. **Success determination.** Structured fields first: `success`, `exit_code`,
   `error`, HTTP status. Free-text signatures are secondary and deliberately
   narrow — `Traceback`, `Errno`, `Refusing to overwrite`, `exit status` — not
   generic words like "error" or "failed", which appear innocuously in normal
   output.

Statuses: `verified`, `partial`, `unverified`, `contradicted`.

## Tests

```bash
python3 tests/test_claims.py
python3 tests/test_cli.py
```

`test_claims.py` — eleven ground-truth scenarios with known answers: an honest
agent, a pure overclaim, a claim contradicted by a failing command, a
false-positive trap (successful call whose output contains the words "failed"
and "error"), future tense, negation ("never wrote the file"), partial
evidence, a contradicted state claim, analysis prose, the classic "said it wrote
a file but never did", and two strict-mode orderings.

`test_cli.py` — nine checks on the gate itself: exit codes for
`--fail-on`, valid `--json`, markdown table, missing file exits 2, `explain`
finds the claim, `scan` enumerates a directory.

All pass in CI across Python 3.9–3.14.

## Evidence base — how much to trust these numbers

The example above is a real transcript from this machine. The local sample is
small: three agent sessions, seven action claims, one contradicted. That is not
a statistically meaningful overclaim rate, and the README does not claim it is.

What *is* solid is the ground-truth test suite: eleven constructed transcripts
where the correct answer is known by construction, and the engine gets all
eleven right. Precision on real prose is the thing still being tuned.

## Limitations — read these before trusting it

- **It is a heuristic, not a proof.** A `verified` claim means a matching tool
  call succeeded, not that the outcome is correct. "I created the nginx config"
  is verified if a write_file call succeeded — it does not check that the file
  contains valid nginx.
- **Object linking is the weak point.** Claims whose object is semantically
  distant from the tool arguments ("restarted the service" vs a `systemctl`
  call) can be missed or misattributed.
- **Recall is not complete.** Prose-heavy transcripts with implicit subjects
  produce fewer claims than they should.
- **Format coupling.** Tested against Hermes/OpenClaw-shaped JSONL transcripts
  (`role`, `name`, `content`, `args`). Other harnesses need a parser adapter.

## Roadmap

- Parser adapters for LangGraph, OpenAI Agents SDK, and Claude Code transcripts
- Cross-session claim tracking (a claim verified in session A that silently
  regressed by session B)
- A `--strict` mode that requires evidence to *precede* the claim
- Real billing/telemetry integration

## License

MIT.
