#!/usr/bin/env python3
"""
Changelog writer agent.
Reads the git diff of the latest commit, asks Claude to summarise it
in Keep a Changelog format, and prepends the entry to CHANGELOG.md.
"""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import groq
from groq import Groq

# ── Config ────────────────────────────────────────────────────────────────────

CHANGELOG_PATH = Path("CHANGELOG.md")
MAX_DIFF_CHARS = 12_000   # truncate huge diffs so we stay inside context limits
MODEL = "openai/gpt-oss-20b"

SYSTEM_PROMPT = """You are a technical writer that produces changelog entries.

Given a git diff and commit metadata, write a concise changelog entry in
Keep a Changelog format (https://keepachangelog.com).

Rules:
- Use only these sections (omit any that are empty):
    ### Added, ### Changed, ### Deprecated, ### Removed, ### Fixed, ### Security
- Each bullet is one short sentence in the imperative mood, max ~15 words.
- Ignore whitespace-only changes, lock-file churns, and auto-generated files.
- Do NOT include a version header or date — those are added by the script.
- Output only the markdown sections, nothing else.

Example output:
### Added
- Support environment variable `TIMEOUT_MS` for configuring request timeouts.

### Fixed
- Prevent crash when config file is missing on first run.
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[warn] Command failed: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
    return result.stdout.strip()


def get_diff() -> str:
    diff = run(["git", "diff", "HEAD~1", "HEAD"])
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n[diff truncated]"
    return diff


def get_commit_info() -> dict:
    return {
        "sha":     os.environ.get("COMMIT_SHA", run(["git", "rev-parse", "HEAD"]))[:8],
        "message": os.environ.get("COMMIT_MSG",  run(["git", "log", "-1", "--pretty=%s"])),
        "author":  os.environ.get("AUTHOR",      run(["git", "log", "-1", "--pretty=%an"])),
        "date":    date.today().isoformat(),
    }


def ask_claude(diff: str, commit: dict) -> str:
    client = Groq(
    api_key=os.environ.get("GROQ_API_KEY"),
)

    user_message = f"""Commit: {commit['sha']} — {commit['message']}
Author: {commit['author']}

Git diff:
```diff
{diff}
```

Write the changelog entry for this commit."""

    message = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
    )
    return message.choices[0].message.content.strip()


def prepend_to_changelog(entry: str, commit: dict) -> None:
    header = f"## [{commit['sha']}] - {commit['date']}\n"
    new_section = header + entry + "\n"

    if CHANGELOG_PATH.exists():
        existing = CHANGELOG_PATH.read_text()
        # Insert after the top-level CHANGELOG heading if present, else prepend
        if existing.startswith("# "):
            first_newline = existing.index("\n") + 1
            updated = existing[:first_newline] + "\n" + new_section + "\n" + existing[first_newline:]
        else:
            updated = new_section + "\n" + existing
    else:
        updated = "# Changelog\n\nAll notable changes to this project are documented here.\n\n" + new_section

    CHANGELOG_PATH.write_text(updated)
    print(f"[ok] Prepended entry for {commit['sha']} to {CHANGELOG_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    commit = get_commit_info()
    print(f"[info] Processing commit {commit['sha']}: {commit['message']}")

    diff = get_diff()
    if not diff:
        print("[info] Empty diff — nothing to document.")
        return

    print("[info] Calling Claude…")
    entry = ask_claude(diff, commit)
    print("[info] Claude response:\n" + entry)

    prepend_to_changelog(entry, commit)


if __name__ == "__main__":
    main()