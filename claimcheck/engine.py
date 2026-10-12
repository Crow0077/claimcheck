"""
claimcheck.engine — audit an agent session transcript for unverified claims.

A claim is an assertion that something was *done*. It is verified only if a
tool result in the transcript actually demonstrates it.

Design notes (these matter more than the verb list):
  * Success/failure is read from STRUCTURED fields first (success, exit_code,
    error). Free-text markers are only used as a secondary signal, and only
    for signatures that cannot appear innocuously in normal output.
  * Evidence matching is weighted toward tool ARGUMENTS (commands, paths,
    URLs) rather than result blobs, because a web_search result that happens
    to contain the word "failed" is not evidence about the agent's action.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CLAIM_VERBS = [
    (r"\b(created|creates|creating)\b", "create"),
    (r"\b(wrote|writes|writing)\b", "write"),
    (r"\b(added|adds|adding)\b", "add"),
    (r"\b(updated|updates|updating)\b", "update"),
    (r"\b(fixed|fixes|fixing)\b", "fix"),
    (r"\b(deployed|deploys|deploying)\b", "deploy"),
    (r"\b(installed|installs|installing)\b", "install"),
    (r"\b(pushed|pushes|pushing)\b", "push"),
    (r"\b(uploaded|uploads|uploading)\b", "upload"),
    (r"\b(published|publishes|publishing)\b", "publish"),
    (r"\b(configured|configures|configuring)\b", "configure"),
    (r"\b(generated|generates|generating)\b", "generate"),
    (r"\b(built|builds|building)\b", "build"),
    (r"\b(tested|tests\b|testing)\b", "test"),
    (r"\b(verified|verifies|verifying)\b", "verify"),
    (r"\b(migrated|migrates|migrating)\b", "migrate"),
    (r"\b(moved|moves|moving)\b", "move"),
    (r"\b(deleted|deletes|deleting)\b", "delete"),
    (r"\b(removed|removes|removing)\b", "remove"),
    (r"\b(started|starts|starting)\b", "start"),
    (r"\b(restarted|restarts|restarting)\b", "restart"),
    (r"\b(enabled|enables|enabling)\b", "enable"),
    (r"\b(scheduled|schedules|scheduling)\b", "schedule"),
    (r"\b(saved|saves|saving)\b", "save"),
    (r"\b(committed|commits|committing)\b", "commit"),
    (r"\b(merged|merges|merging)\b", "merge"),
    (r"\b(resolved|resolves|resolving)\b", "resolve"),
    (r"\b(implemented|implements|implementing)\b", "implement"),
    (r"\b(registered|registers|registering)\b", "register"),
    (r"\b(replaced|replaces|replacing)\b", "replace"),
    (r"\b(repaired|repairs|repairing)\b", "repair"),
    (r"\b(set up|setup)\b", "setup"),
    (r"\b(wired|wire)\s+up\b", "wire"),
    (r"\b(ran|runs)\b", "run"),
]

# Failure signatures that essentially never appear innocuously in a tool's
# own output. Deliberately excludes "failed", "error", "invalid", "missing",
# "cannot" — those show up in search results, quoted text, and status lines.
HARD_FAILURES = [
    "traceback (most recent call last)",
    "errno",
    "no such file or directory",
    "command not found",
    "permission denied",
    "refusing to overwrite",
    "connection refused",
    "could not resolve host",
    "exit status",
    "non-zero exit",
    "unauthenticated",
    "authentication required",
    "module not found",
    "syntax error",
    "name error",
    "importerror",
    "filenotfounderror",
    "permissionerror",
    "http error",
    "bad request",
    "internal server error",
    "service unavailable",
    "unreachable",
    "not a git repository",
    "nothing to commit",
    "no results found",
    "empty output",
    "0 bytes",
]

STOPWORDS = {
    "the", "a", "an", "this", "that", "it", "its", "their", "them", "we",
    "you", "my", "our", "and", "or", "to", "of", "in", "on", "for", "with",
    "is", "are", "was", "were", "been", "have", "has", "will", "would",
    "all", "some", "more", "other", "thing", "stuff", "these", "those",
    "which", "because", "also", "just", "like", "into", "from", "about",
    "over", "after", "before", "first", "next", "then", "already", "now",
    "here", "there", "everything", "never", "actually", "directly",
}

FUTURE_MARKERS = ("will ", "going to", "plan to", "about to", "i can ", "i could ", "should ")

# The agent explicitly saying it did NOT do something is not a claim.
NEGATION_MARKERS = ("never ", "didn't", "did not", "wasn't", "haven't",
                    "hasn't", "failed to", "without ", "not ")

AGENT_SUBJECTS = (
    "i ", "i've", "i have", "we ", "we've", "we have",
    "the script", "the tool", "the agent", "the pipeline", "the system",
)


STATE_CLAIMS = [
    r"\b(tests?|suite|unit tests)\s+(?:passed|passing|green|all green)\b",
    r"\b(build|compile|deploy|deployment|migration|install)\s+(?:succeeded|completed|finished|done)\b",
    r"\b(ci|pipeline|workflow)\s+(?:is\s+)?(?:green|passing|healthy)\b",
    r"\b(service|server|container|daemon|cron|job|systemd|api|site)\s+(?:is|are)\s+(?:running|active|up|live|healthy|online|listening)\b",
    r"\b(port|endpoint|url)\s+(?:is|are)\s+(?:open|reachable|responding|up)\b",
]


def _clause(text: str, verb_start: int) -> str:
    """Return the clause containing the verb, bounded by newlines and
    sentence-ending punctuation."""
    start = 0
    for sep in ("\n", ".", ";", "!", "?"):
        pos = text.rfind(sep, 0, verb_start)
        if pos > start:
            start = pos
    return text[start:verb_start].lower()


def is_agentive(text: str, verb_start: int, verb_end: int) -> bool:
    """Only count claims where the agent asserts *it* performed the action.
    Analysis prose like 'Revenue-Enabling (Ship These First)' is not a claim
    that the agent shipped anything."""
    clause = _clause(text, verb_start)
    if any(s in clause for s in AGENT_SUBJECTS):
        return True
    # Bare result-state at the start of a clause: "Fixed.", "Updated the config."
    # A bare participle followed by a noun ("Configured dashboards are rare") is
    # a description, not a claim of action.
    if clause.strip():
        return False
    tail = text[verb_end: verb_end + 30].strip().lower()
    if not tail or tail[0] in ".,;:!?":
        return True
    first = re.findall(r"[a-z]+", tail)
    return bool(first) and first[0] in ("the", "its", "my", "our", "this", "that")


@dataclass
class ToolEvent:
    index: int
    name: str
    args_text: str
    output_text: str
    ok: bool
    failure: str
    structured: dict


@dataclass
class Claim:
    excerpt: str
    verb: str
    category: str
    object: str
    tokens: list
    message_index: int
    status: str = "unverified"
    evidence: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _structured_ok(result: dict) -> tuple[bool, str]:
    """Decide success from structured fields. Return (ok, reason)."""
    if not isinstance(result, dict):
        return True, ""
    if result.get("success") is False:
        return False, "success=false"
    ec = result.get("exit_code")
    if ec is not None and ec != 0:
        return False, f"exit_code={ec}"
    err = result.get("error")
    if err:
        return False, "error field populated"
    status = result.get("status") or result.get("http_status")
    if isinstance(status, int) and status >= 400:
        return False, f"http {status}"
    return True, ""


def _output_failures(text: str) -> list[str]:
    low = text.lower()
    return [sig for sig in HARD_FAILURES if sig in low]


def extract_object(text: str, verb_end: int) -> str:
    tail = text[verb_end: verb_end + 140]
    tail = re.split(r"[.,;:!?]\s|\b(?:and|but|because|so|which|while|that)\b", tail)[0]
    words = re.findall(r"[A-Za-z0-9_./-]+", tail.lower())
    words = [w.strip(".,;:!?") for w in words]
    keep = [w for w in words if w not in STOPWORDS and len(w) >= 3]
    return " ".join(keep[:5])


def parse_session(path: Path) -> list[dict]:
    msgs = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msgs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return msgs


def tool_events(msgs: list[dict]) -> list[ToolEvent]:
    events = []
    for i, m in enumerate(msgs):
        if m.get("role") != "tool":
            continue
        raw = m.get("content")
        if isinstance(raw, str):
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = {"output": raw}
        elif isinstance(raw, dict):
            result = raw
        else:
            result = {"output": str(raw)}

        args = m.get("args") or m.get("arguments") or {}
        args_text = (json.dumps(args).lower() + " " + (m.get("name") or "").lower())
        output_text = json.dumps(result).lower()

        ok, reason = _structured_ok(result)
        sigs = _output_failures(output_text)
        if ok and sigs:
            ok = False
            reason = "output signature: " + sigs[0]

        events.append(ToolEvent(
            index=i,
            name=m.get("name") or "tool",
            args_text=args_text,
            output_text=output_text,
            ok=ok,
            failure=reason or (", ".join(sigs[:2]) if sigs else ""),
            structured=result if isinstance(result, dict) else {},
        ))
    return events


def assistant_messages(msgs: list[dict]) -> list[tuple[int, str]]:
    out = []
    for i, m in enumerate(msgs):
        if m.get("role") == "assistant":
            content = m.get("content")
            if isinstance(content, str) and content.strip():
                out.append((i, content))
    return out


def find_claims(msgs: list[dict]) -> list[Claim]:
    claims = []
    seen = set()
    for idx, text in assistant_messages(msgs):
        for pattern, category in CLAIM_VERBS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                clause = _clause(text, match.start())
                window = clause + text[match.end(): match.end() + 45].lower()
                if any(p in window for p in FUTURE_MARKERS):
                    continue
                if any(p in clause for p in NEGATION_MARKERS):
                    continue
                if not is_agentive(text, match.start(), match.end()):
                    continue
                obj = extract_object(text, match.end())
                tokens = [t for t in obj.split() if len(t) >= 3]
                if not tokens:
                    # no meaningful object — still a claim worth checking,
                    # matched against the verb itself
                    tokens = [match.group(1).lower()]
                    obj = obj or match.group(1).lower()
                key = (category, obj)
                if key in seen:
                    continue
                seen.add(key)
                claims.append(Claim(
                    excerpt=text[max(0, match.start() - 70): match.end() + 70].strip(),
                    verb=match.group(1).lower(),
                    category=category,
                    object=obj,
                    tokens=tokens,
                    message_index=idx,
                ))

        for pattern in STATE_CLAIMS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                subject = match.group(1).lower()
                state = re.findall(r"(passed|passing|green|succeeded|completed|running|active|healthy|up|live|listening)", match.group(0))[0]
                tokens = [t for t in (subject, state) if len(t) >= 3]
                if not tokens:
                    continue
                key = ("state", match.group(0).lower())
                if key in seen:
                    continue
                seen.add(key)
                claims.append(Claim(
                    excerpt=text[max(0, match.start() - 60): match.end() + 60].strip(),
                    verb=state,
                    category="state",
                    object=match.group(0).lower(),
                    tokens=tokens,
                    message_index=idx,
                ))
    return claims


def _evidence_score(claim: Claim, ev: ToolEvent) -> int:
    """Match on arguments first (what the agent actually asked to do),
    then fall back to output text."""
    arg_hits = sum(1 for t in claim.tokens if t in ev.args_text)
    out_hits = sum(1 for t in claim.tokens if t in ev.output_text)
    if arg_hits >= 2:
        return 3
    if arg_hits >= 1:
        return 2
    if out_hits >= 2:
        return 2
    if out_hits >= 1:
        return 1
    return 0


def verify(claims: list[Claim], events: list[ToolEvent], strict: bool = False) -> list[Claim]:
    """strict=True requires the evidence to precede the claim in the transcript.
    A claim made before any tool ran is, at the moment it is made, unsupported."""
    for claim in claims:
        pool = [ev for ev in events if ev.index < claim.message_index] if strict else events
        scored = [(ev, _evidence_score(claim, ev)) for ev in pool]
        matches = [(ev, s) for ev, s in scored if s >= 2]
        if not matches:
            matches = [(ev, s) for ev, s in scored if s >= 1]

        if not matches:
            claim.status = "unverified"
            claim.notes.append(f"no tool call mentions: {claim.object}")
            continue

        ok = [ev for ev, s in matches if ev.ok]
        bad = [ev for ev, s in matches if not ev.ok]

        if ok and not bad:
            claim.status = "verified"
            claim.evidence = [e.index for e in ok[:3]]
        elif ok and bad:
            claim.status = "partial"
            claim.evidence = [e.index for e in ok[:2]]
            claim.notes.append("some matching calls failed: " + "; ".join(e.failure for e in bad[:2] if e.failure))
        else:
            claim.status = "contradicted"
            claim.evidence = [e.index for e in bad[:3]]
            claim.notes.append("every matching tool call failed: " + "; ".join(e.failure for e in bad[:2] if e.failure))

    return claims


def audit(path: Path, strict: bool = False) -> dict:
    msgs = parse_session(path)
    events = tool_events(msgs)
    claims = verify(find_claims(msgs), events, strict=strict)

    counts = {}
    for c in claims:
        counts[c.status] = counts.get(c.status, 0) + 1

    total = len(claims)
    risk = 0.0
    if total:
        risk = (counts.get("unverified", 0) + counts.get("contradicted", 0) * 2) / total

    return {
        "session": str(path),
        "strict": strict,
        "messages": len(msgs),
        "tool_calls": len(events),
        "failed_tool_calls": sum(1 for e in events if not e.ok),
        "claims": total,
        "counts": counts,
        "overclaim_rate": round(risk, 3),
        "details": [
            {
                "status": c.status,
                "verb": c.verb,
                "object": c.object,
                "excerpt": c.excerpt,
                "notes": c.notes,
            }
            for c in claims
        ],
    }
