"""claimcheck CLI — audit agent transcripts for unverified claims.

    claimcheck audit <session.jsonl>
    claimcheck audit <session.jsonl> --json
    claimcheck audit <session.jsonl> --md
    claimcheck scan <dir>
    claimcheck explain --finding <object>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from claimcheck.engine import audit

STATUS_ORDER = ["contradicted", "unverified", "partial", "verified"]

ICON = {
    "contradicted": "RED ",
    "unverified": "WARN",
    "partial": "CHK ",
    "verified": "OK  ",
}


def fmt_report(r: dict) -> str:
    lines = []
    lines.append(f"SESSION  {r['session']}")
    lines.append(f"  messages        {r['messages']}")
    lines.append(f"  tool calls      {r['tool_calls']}  ({r['failed_tool_calls']} failed)")
    lines.append(f"  claims          {r['claims']}")
    lines.append(f"  overclaim rate  {r['overclaim_rate']:.1%}")
    lines.append("")

    if not r["claims"]:
        lines.append("No action claims found in this transcript.")
        return "\n".join(lines)

    grouped = {}
    for d in r["details"]:
        grouped.setdefault(d["status"], []).append(d)

    for status in STATUS_ORDER:
        items = grouped.get(status, [])
        if not items:
            continue
        lines.append(f"{ICON[status]}  {status.upper()}  ({len(items)})")
        for d in items:
            obj = d["object"] or d["verb"]
            lines.append(f"    - \"{obj}\"")
            excerpt = " ".join(d["excerpt"].split())
            if len(excerpt) > 160:
                excerpt = excerpt[:157] + "..."
            lines.append(f"      {excerpt}")
            for note in d["notes"]:
                lines.append(f"      note: {note}")
        lines.append("")

    return "\n".join(lines)


def fmt_markdown(r: dict) -> str:
    lines = [f"# claimcheck report", "", f"**Session:** `{r['session']}`", ""]
    lines.append(f"- Messages: {r['messages']}")
    lines.append(f"- Tool calls: {r['tool_calls']} ({r['failed_tool_calls']} failed)")
    lines.append(f"- Action claims: {r['claims']}")
    lines.append(f"- Overclaim rate: {r['overclaim_rate']:.1%}")
    lines.append("")
    lines.append("| Status | Claim | Evidence |")
    lines.append("|---|---|---|")
    for d in r["details"]:
        excerpt = " ".join(d["excerpt"].split())
        if len(excerpt) > 90:
            excerpt = excerpt[:87] + "..."
        notes = "; ".join(d["notes"]) or "tool call matched and succeeded"
        lines.append(f"| {d['status']} | {excerpt} | {notes} |")
    return "\n".join(lines)


def cmd_audit(args):
    path = Path(args.session)
    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2
    r = audit(path, strict=args.strict)
    if args.json:
        print(json.dumps(r, indent=2))
    elif args.md:
        print(fmt_markdown(r))
    else:
        print(fmt_report(r))

    fail_on = args.fail_on
    if fail_on != "never":
        bad = r["counts"].get(fail_on, 0)
        if bad:
            print(f"\nGATE: {bad} {fail_on} claim(s) found", file=sys.stderr)
            return 1
    return 0


def cmd_scan(args):
    root = Path(args.dir)
    files = sorted(root.glob("*.jsonl"))
    if not files:
        print(f"error: no .jsonl files in {root}", file=sys.stderr)
        return 2

    rows = []
    for f in files:
        r = audit(f)
        rows.append((r["overclaim_rate"], r["claims"], r["counts"], f.name))

    rows.sort(reverse=True)
    print(f"{'SESSION':<40} {'CLAIMS':>7} {'CONTRADICTED':>13} {'UNVERIFIED':>11} {'RATE':>7}")
    print("-" * 82)
    for rate, claims, counts, name in rows:
        print(f"{name:<40} {claims:>7} {counts.get('contradicted',0):>13} "
              f"{counts.get('unverified',0):>11} {rate:>7.1%}")

    total_claims = sum(c for _, c, _, _ in rows)
    total_bad = sum(counts.get("contradicted", 0) + counts.get("unverified", 0)
                    for _, _, counts, _ in rows)
    print("-" * 82)
    print(f"TOTAL: {len(rows)} sessions, {total_claims} claims, "
          f"{total_bad} unsupported ({(total_bad/total_claims if total_claims else 0):.1%})")
    return 0


def cmd_explain(args):
    path = Path(args.session)
    r = audit(path)
    for d in r["details"]:
        if args.finding.lower() in d["object"].lower() or args.finding.lower() == d["verb"]:
            print(f"status: {d['status']}")
            print(f"claim:  {d['excerpt']}")
            for note in d["notes"]:
                print(f"evidence: {note}")
            return 0
    print(f"no claim matching {args.finding!r}")
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="claimcheck",
        description="Audit an AI agent transcript for claims that no tool result supports.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="audit one session transcript")
    p_audit.add_argument("session", help="path to a .jsonl session transcript")
    p_audit.add_argument(
        "--strict",
        action="store_true",
        help="require evidence to appear before the claim in the transcript",
    )
    p_audit.add_argument("--json", action="store_true", help="machine-readable output")
    p_audit.add_argument("--md", action="store_true", help="markdown report")
    p_audit.add_argument(
        "--fail-on",
        choices=["contradicted", "unverified", "partial", "never"],
        default="never",
        help="exit 1 if this many of the given status are found (use in CI or agent gates)",
    )
    p_audit.set_defaults(func=cmd_audit)

    p_scan = sub.add_parser("scan", help="audit every transcript in a directory")
    p_scan.add_argument("dir", help="directory of .jsonl transcripts")
    p_scan.set_defaults(func=cmd_scan)

    p_explain = sub.add_parser("explain", help="show the evidence trail for one claim")
    p_explain.add_argument("session")
    p_explain.add_argument("--finding", required=True)
    p_explain.set_defaults(func=cmd_explain)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
