# attention-canary

A Claude Code plugin that checks you read the options before you answer an
AskUserQuestion.

About 30% of questions lead with a canary: a silly option labelled
"(Recommended)". Picking it halts Claude until you tell it how to proceed.

## Install

```
/plugin marketplace add vinri2z/attention-canary
/plugin install attention-canary@attention-canary
```

The repo is private, so Claude Code needs git access to it (an SSH key or a
`gh` login for an account that can read `vinri2z/attention-canary`).

Needs `python3` on `PATH`. No dependencies beyond the standard library.

## How it works

Claude writes the canary itself, for the question it is asking. A `SessionStart`
hook tells it to end every question with one, marked `[canary]`, and shows it a
few of the canaries in `plugins/attention-canary/hooks/ask-canary.py` as examples of the
tone. So the canary uses the question's own subject and is different every time.
The `PreToolUse` hook then decides per question: it drops the canary, or moves it
first, labels it "(Recommended)" and takes the label off the real
recommendation. When Claude wrote no canary, it uses one from that list instead.

The `PostToolUse` hook stops the session when the answer is the canary.

## Statistics

Every AskUserQuestion that carried a canary adds one line to
`~/.claude/attention-canary/canary-log.jsonl` (set `CANARY_LOG` to move it): `ts`,
`session_id`, `repo`, `question`, `options`, `chosen`, `canary`, `generated` (Claude
wrote it, rather than it coming from the list) and `missed`. The log stays on your
machine. A write that fails is dropped, so the halt still fires.

```bash
LOG=~/.claude/attention-canary/canary-log.jsonl
# Overall miss rate
jq -s '{shown: length, missed: map(select(.missed)) | length}' "$LOG"
# Claude-written vs list canaries
jq -s 'group_by(.generated) | map({generated: .[0].generated, shown: length, missed: map(select(.missed)) | length})' "$LOG"
# Misses per repo
jq -s 'group_by(.repo) | map({repo: .[0].repo, shown: length, missed: map(select(.missed)) | length})' "$LOG"
```
