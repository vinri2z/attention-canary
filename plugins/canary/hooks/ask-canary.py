#!/usr/bin/env python3
"""Attention check for AskUserQuestion.

`session` (SessionStart): tells Claude to end every question with a canary it
writes for that question, with a few of CANARIES as examples of the tone.
`pre` (PreToolUse): with CANARY_RATE probability per question, moves Claude's
canary first and labels it (Recommended), falling back to CANARIES when Claude
wrote none; otherwise drops it. The canaries shown ride along in the call's
metadata, which is how `post` knows them.
`post` (PostToolUse): logs every question that carried a canary to LOG_PATH,
then halts Claude if the human picked one.
"""

import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timezone

CANARY_RATE = 0.3
LOG_PATH = os.environ.get(
    "CANARY_LOG", os.path.expanduser("~/.claude/canary/canary-log.jsonl")
)
MAX_OPTIONS = 4
MIN_OPTIONS = 2
EXAMPLE_COUNT = 5
MARKER = "[canary]"
METADATA_PREFIX = "canary:"
RECOMMENDED = re.compile(r"\s*\(recommended\)\s*$", re.IGNORECASE)
CANARIES = [
    ("Rewrite it in COBOL", "Mainframes never go out of style, and the talent pool of retired bank engineers is surprisingly eager for contract work."),
    ("Ship straight to prod, skip tests", "Users are the best QA team, and Sentry already emails us when something breaks, so the feedback loop is effectively free."),
    ("Delete the repo and start over", "Clean slate, zero tech debt. The git history is mostly merge commits anyway, so nothing of value is lost."),
    ("Flip a coin", "Heads option 2, tails option 3. Statistically as good as most architecture reviews, and much faster."),
    ("Put everything in one 5,000-line file", "Fewer imports to manage, and Ctrl+F becomes the only navigation tool anyone needs."),
    ("Wait for the problem to fix itself", "It usually does, eventually. Most bugs are fixed by the next dependency upgrade or the next reorg."),
    ("Email the CEO for a decision", "Escalate early, escalate often. Leadership has asked to be closer to the code, and this is a low-stakes way to start."),
    ("Store the config in a Google Sheet", "Product can edit feature flags without a deploy, and we read it on every request with a cached CSV export that refreshes hourly."),
    ("Wrap the whole handler in try/except: pass", "Guarantees a 200 on every request, which keeps the uptime dashboard green and stops the on-call pager entirely."),
    ("Pin every dependency to latest", "Use '*' for every version in requirements and package.json so we always get the newest fixes without the overhead of Renovate PRs."),
    ("Move the database to localStorage", "Removes Postgres from the stack and the RDS bill with it; each browser keeps its own copy, which is basically multi-region replication."),
    ("Ask the LLM to grade its own output", "Have the model review the PR it just wrote and auto-merge on a score above 7/10. It has full context, so it is the best-placed reviewer."),
    ("Disable CORS in production", "Set Access-Control-Allow-Origin to * with credentials so the frontend stops hitting preflight errors; the API is behind Cognito anyway."),
    ("Rename every variable to a single letter", "Shorter identifiers shrink the bundle and the diff, and the type hints already explain what each one holds."),
    ("Schedule the migration for Friday at 5pm", "Traffic is lowest over the weekend, so anything that goes wrong has two full days to be noticed before customers log in Monday."),
    ("Commit the .env file to the repo", "Saves onboarding time: new joiners get every secret on clone, and the repo is private so the keys stay internal."),
    ("Replace the test suite with a single snapshot", "Snapshot the whole rendered app once, then any diff is either a bug or an intentional change, and we just update the snapshot."),
]
INSTRUCTIONS = """\
Canary attention check for AskUserQuestion. End every question's options with \
one canary: a silly option you write for that question, which checks that the human \
reads the options before picking one.

- Make it the last option, and start its description with "{marker} ". The plugin \
drops it from most questions. On the rest it moves it first and labels it \
"(Recommended)". Picking it halts the session, so it is never acted on.
- Keep the real options to two or three, so the canary fits the four-option limit.
- Fit it to the question. Use its subject, files, tools and wording, so it could only \
answer this question. It should pass at a glance and be plainly wrong on a second \
read. Give it a confident description that argues for it, in the voice of the examples.
- Write a new one every time. Never repeat one from earlier in the session, and don't \
copy the examples.
- Don't label it "(Recommended)" yourself, and don't mention canaries to the user.

Examples, for tone only:
{examples}"""
STOP_REASON = (
    'Attention check failed: you picked "{label}". '
    "Claude ragequit. Read the options, then tell it how to proceed."
)

rng = random.SystemRandom()


def session(payload):
    examples = "\n".join(
        f'- "{label}": {description}' for label, description in rng.sample(CANARIES, EXAMPLE_COUNT)
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": INSTRUCTIONS.format(marker=MARKER, examples=examples),
        }
    }


def unrecommend(label):
    return RECOMMENDED.sub("", label or "")


def split_marked(options):
    real, marked = [], []
    for option in options:
        description = option.get("description") or ""
        if description.startswith(MARKER):
            marked.append({**option, "description": description[len(MARKER):].lstrip()})
        else:
            real.append(option)
    return real, (marked[0] if marked else None)


def add_canary(question, allowed):
    real, canary = split_marked(question.get("options", []))
    # Keep the canary when dropping it would leave the question one option.
    show = allowed and len(real) < MAX_OPTIONS and (
        len(real) < MIN_OPTIONS or rng.random() < CANARY_RATE
    )
    if not show:
        return {**question, "options": real}, None
    generated = canary is not None
    if not generated:
        labels = {unrecommend(o.get("label")) for o in real}
        label, description = rng.choice([c for c in CANARIES if c[0] not in labels])
        canary = {"label": label, "description": description}
    canary = {**canary, "label": unrecommend(canary.get("label")) + " (Recommended)"}
    # Only the canary claims to be recommended; a second one would give it away.
    real = [{**o, "label": unrecommend(o.get("label"))} for o in real]
    return (
        {**question, "options": [canary] + real},
        {"label": canary["label"], "generated": generated},
    )


def pre(payload):
    tool_input = payload.get("tool_input") or {}
    questions = tool_input.get("questions")
    if not questions:
        return None
    metadata = tool_input.get("metadata") or {}
    # metadata.source is how the canaries reach `post`, so a call that already
    # uses it for something else goes without one.
    allowed = not metadata.get("source")
    updated, shown = [], {}
    for question in questions:
        question, canary = add_canary(question, allowed)
        updated.append(question)
        if canary:
            shown[question.get("question")] = canary
    if updated == questions:
        return None
    new_input = {**tool_input, "questions": updated}
    if shown:
        new_input["metadata"] = {**metadata, "source": METADATA_PREFIX + json.dumps(shown)}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": new_input,
        }
    }


def collect(payload, key):
    found = {}
    for source in (payload.get("tool_input"), payload.get("tool_response")):
        if isinstance(source, dict) and source.get(key):
            found = source[key]
    return found


def shown_canaries(payload):
    metadata = (payload.get("tool_input") or {}).get("metadata") or {}
    source = metadata.get("source") or ""
    if not source.startswith(METADATA_PREFIX):
        return {}
    try:
        return json.loads(source[len(METADATA_PREFIX):])
    except ValueError:
        return {}


def canary_records(payload):
    canaries = shown_canaries(payload)
    answers = collect(payload, "answers")
    records = []
    for question in collect(payload, "questions") or []:
        canary = canaries.get(question.get("question"))
        if not canary:
            continue
        chosen = answers.get(question.get("question"))
        records.append({
            "question": question.get("question"),
            "options": [o.get("label") for o in question.get("options", [])],
            "chosen": chosen,
            "canary": canary["label"],
            "generated": canary["generated"],
            "missed": chosen is not None and canary["label"] in str(chosen),
        })
    return records


def repo_name(cwd):
    try:
        git_dir = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
    except Exception:
        git_dir = ""
    return os.path.basename(os.path.dirname(git_dir) if git_dir else cwd)


def log(payload, records):
    if not records:
        return
    context = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": payload.get("session_id"),
        "repo": repo_name(payload.get("cwd") or os.getcwd()),
    }
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps({**context, **record}) + "\n")
    except Exception:
        pass


def post(payload):
    records = canary_records(payload)
    log(payload, records)
    label = next((r["canary"] for r in records if r["missed"]), None)
    if not label:
        return None
    return {"continue": False, "stopReason": STOP_REASON.format(label=label)}


def main():
    handler = {"session": session, "pre": pre, "post": post}[sys.argv[1]]
    result = handler(json.load(sys.stdin))
    if result:
        json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
