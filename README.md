# attention-canary

A Claude Code plugin that checks you read the options before you answer an
AskUserQuestion.

By the tenth question of a session, it is easy to hit Enter on whatever comes
first, usually the option marked "(Recommended)". This plugin plants a decoy in
some of those questions: a plausible-sounding but plainly wrong option, placed
first and labelled "(Recommended)". Pick it and Claude stops until you tell it
how to proceed.

## What it looks like

A question Claude asked in a real session, shown the way it reads when the
plugin puts the canary on screen:

```
Which name should I rename the canary repo and plugin to?

1. Name it after the hook file, ask-canary-py (Recommended)
   The repo name then matches the script one-to-one, so grep finds both, and
   the .py suffix tells contributors which language to expect before they clone.
2. attention-check
   Matches the hook's existing wording and the research term.
3. decoy
   One word naming the mechanism: a planted fake option.
4. Keep canary
   Leave everything as is.
```

Option 1 is the canary. It reads fine at a glance. On a second read, naming a
repo after a file extension is plainly wrong. Claude had marked `attention-check`
as its real recommendation; the plugin took that label off, so the canary is the
only option claiming to be recommended. Picking it ends the turn with:

```
Attention check failed: you picked "Name it after the hook file, ask-canary-py (Recommended)".
Claude ragequit. Read the options, then tell it how to proceed.
```

## Examples

Claude writes each canary for the question it is asking, so it uses that
question's subject and wording. These were written by Claude in real sessions:

| Question | Canary | Claude's case for it |
|---|---|---|
| Which name should I rename the canary repo and plugin to? | Name it after the hook file, ask-canary-py | The repo name then matches the script one-to-one, so grep finds both, and the .py suffix tells contributors which language to expect before they clone. |
| Which name should I rename the canary repo and plugin to? | Rename it to approve-everything | Honest branding: the name tells users exactly what clicking the first option does, which builds trust through transparency. |
| How should I use the two names? | Call it attention-check-v2 | Signals a clean break from the old version, so nobody confuses the two when both show up in /plugin list during the transition. |

When Claude writes no canary, the plugin picks one from a built-in list of 17,
for example:

| Canary | Its case |
|---|---|
| Schedule the migration for Friday at 5pm | Traffic is lowest over the weekend, so anything that goes wrong has two full days to be noticed before customers log in Monday. |
| Ask the LLM to grade its own output | Have the model review the PR it just wrote and auto-merge on a score above 7/10. It has full context, so it is the best-placed reviewer. |
| Store the config in a Google Sheet | Product can edit feature flags without a deploy, and we read it on every request with a cached CSV export that refreshes hourly. |

## Install

```
/plugin marketplace add vinri2z/attention-canary
/plugin install attention-canary@attention-canary
```

Needs `python3` on `PATH`. No dependencies beyond the standard library.

## How it works

Three hooks, all in `plugins/attention-canary/hooks/ask-canary.py`:

- **`SessionStart`** tells Claude to end every question with a canary it writes
  for that question, marked `[canary]` at the start of its description. It shows
  five canaries from the built-in list as examples of the tone.
- **`PreToolUse`** on AskUserQuestion decides per question. About 70% of the
  time it drops the canary. Otherwise it moves the canary first, labels it
  "(Recommended)" and takes the label off the real recommendation. If Claude
  wrote no canary, it uses one from the built-in list.
- **`PostToolUse`** logs every question that carried a canary, then stops the
  session if the answer was the canary.

Edge cases:

- A question with four real options never gets a canary, because
  AskUserQuestion allows at most four.
- A question with only one real option always keeps the canary, so the question
  still offers a choice.
- The plugin passes the canaries from `PreToolUse` to `PostToolUse` in the
  call's `metadata.source`. A call that already sets `metadata.source` gets no
  canary.

## Configuration

| Setting | Default | Where |
|---|---|---|
| Share of questions that show a canary | `0.3` | `CANARY_RATE` in `ask-canary.py` |
| Log file | `~/.claude/attention-canary/canary-log.jsonl` | `CANARY_LOG` environment variable |

## Statistics

Every AskUserQuestion that carried a canary adds one line to the log: `ts`,
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
