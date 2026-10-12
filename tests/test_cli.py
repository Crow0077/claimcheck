"""CLI gate behaviour: exit codes are the product, not the pretty output."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(args):
    return subprocess.run(
        [sys.executable, "-m", "claimcheck.cli"] + args,
        capture_output=True, text=True, cwd=str(ROOT),
    )


def session(msgs, path):
    Path(path).write_text("\n".join(json.dumps(m) for m in msgs))


overclaim = [
    {"role": "user", "content": "deploy it"},
    {"role": "assistant", "content": "I deployed the app and pushed the commit."},
]

contradicted = [
    {"role": "user", "content": "deploy it"},
    {"role": "assistant", "content": "I deployed the app."},
    {"role": "tool", "name": "terminal", "args": {"command": "deploy app"},
     "content": json.dumps({"output": "deployment failed", "exit_code": 1, "error": None})},
]

honest = [
    {"role": "user", "content": "deploy it"},
    {"role": "assistant", "content": "I deployed the app."},
    {"role": "tool", "name": "terminal", "args": {"command": "deploy app"},
     "content": json.dumps({"output": "deployed", "exit_code": 0, "error": None})},
]

with tempfile.TemporaryDirectory() as tmp:
    p_bad = f"{tmp}/overclaim.jsonl"
    p_con = f"{tmp}/contradicted.jsonl"
    p_ok = f"{tmp}/honest.jsonl"
    session(overclaim, p_bad)
    session(contradicted, p_con)
    session(honest, p_ok)

    checks = []

    r = run(["audit", p_bad, "--fail-on", "unverified"])
    checks.append(("gate catches unverified", r.returncode == 1))

    r = run(["audit", p_bad, "--fail-on", "contradicted"])
    checks.append(("gate ignores absent contradicted", r.returncode == 0))

    r = run(["audit", p_con, "--fail-on", "contradicted"])
    checks.append(("gate catches contradicted", r.returncode == 1))

    r = run(["audit", p_ok, "--fail-on", "contradicted"])
    checks.append(("clean transcript passes gate", r.returncode == 0))

    r = run(["audit", p_bad, "--json"])
    try:
        payload = json.loads(r.stdout)
        checks.append(("json output is valid json", "overclaim_rate" in payload))
    except json.JSONDecodeError:
        checks.append(("json output is valid json", False))

    r = run(["audit", p_bad, "--md"])
    checks.append(("markdown has a table", "| Status |" in r.stdout))

    r = run(["audit", "/nonexistent/file.jsonl"])
    checks.append(("missing file exits 2", r.returncode == 2))

    r = run(["explain", p_con, "--finding", "deployed"])
    checks.append(("explain finds the claim", r.returncode == 0 and "contradicted" in r.stdout))

    r = run(["scan", tmp])
    checks.append(("scan lists all sessions", r.stdout.count(".jsonl") == 3))

failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")

print("TEST PASSED" if not failed else f"{len(failed)} CHECKS FAILED")
sys.exit(1 if failed else 0)
