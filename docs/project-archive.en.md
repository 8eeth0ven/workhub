[简体中文](project-archive.md) | [English](project-archive.en.md)

# Preserve agents, task instructions and deliverables

Work records explain what happened. Project archives also preserve who executed a task, where the session and instructions came from, which project-specific prompt was used, and what can be inspected afterward. They connect a task's sources and outputs without copying an entire conversation.

## A minimal task archive

- The actual agent, a verifiable session ID, a task title and a source reference.
- The original task prompt and its source, versioned by project and purpose.
- A rewritten execution prompt stored separately as `derived`, linked to the original UUID without overwriting the original text.
- Deliverable entry points, editor copies, images, check notes and an evidence-supported status.

Keep missing provenance unknown. Do not infer authorship from a folder, writing style or the agent that later moved a file. Preserve only the task input you need, not full conversations, credentials or a private environment.

## CLI

Provide the variables from your actual project and task, and run these commands from the Workhub repository:

```sh
python3 workhub.py register --path "$WORKHUB_PROJECT_DIR"
python3 workhub.py archive-session --project "$WORKHUB_PROJECT_DIR" \
  --agent codex --session-id "$WORKHUB_SESSION_ID" --title "Current implementation" \
  --source user-provided --source-ref "task-note.txt:1"

python3 workhub.py archive-prompt --project "$WORKHUB_PROJECT_DIR" \
  --title "Original project request" --content-file /path/to/task-prompt.txt \
  --agent codex --session-id "$WORKHUB_SESSION_ID" \
  --purpose implementation --record-type original --prompt-key implementation \
  --source user-provided --source-ref "task-note.txt:1"
```

Keep the returned prompt UUID for a later `--derived-from` link or a deliverable's `--prompt-id`. `prompt-key` is a stable project-scoped key for the same purpose. Changed records append a revision and preserve older versions; identical repeated archival reuses the existing record. To store a derived prompt:

```sh
python3 workhub.py archive-prompt --project "$WORKHUB_PROJECT_DIR" \
  --title "Follow-up execution prompt" --content-file /path/to/derived-prompt.txt \
  --record-type derived --prompt-key implementation \
  --derived-from "$WORKHUB_ORIGINAL_PROMPT_ID"
```

Inputs containing credentials are rejected by default. Explicitly choosing `--redact-sensitive` stores a redacted copy marked as derived, with hashes for the original input and stored content; the original credential is not written to disk. Do not describe the redacted copy as verbatim user text. If you cannot obtain a real session ID, preserve the sources you know rather than inventing an ID.

Instructions reconstructed from files or memory must also be identified as derived, not as original user input. If the original text or its UUID is missing, retain that gap rather than inventing a quotation or link ID.

## Deliverables and status

```sh
python3 workhub.py archive-artifact --project "$WORKHUB_PROJECT_DIR" \
  --title "Release article" --directory "$WORKHUB_PUBLICATION_DIR" \
  --entry article.html --file editor.html --version release-1 --kind publication --status draft \
  --source local-delivery --source-ref checks.md \
  --agent codex --session-id "$WORKHUB_SESSION_ID" \
  --prompt-id "$WORKHUB_ORIGINAL_PROMPT_ID" --image images/cover.png

python3 workhub.py archive-list --project "$WORKHUB_PROJECT_DIR"
```

`--entry` selects a main entry inside the directory. Archival follows only that entry’s local image/CSS dependencies. Repeat `--file` to explicitly attach editor copies or text documents; their own dependencies are collected too. Repeat `--image` for images or `--prompt-id` to associate multiple prompts. Sibling articles in the selected directory are not collected or exposed automatically. Allowed file types are HTML, CSS, images, MD, TXT and PDF. Each snapshot is limited to 256 files and 80 MiB. JavaScript, hidden files and `.env` are not collected, so this is not a full backup of an arbitrary dynamic application.

The main article, editor copy and body fragment count as one editorial work. Series indexes, directory pages and repository-advice pages do not count as articles. Image completeness and publication status are separate questions.

| Status | Evidence needed |
| --- | --- |
| `unknown` | The default: do not infer generation or platform publication without sufficient records. |
| `draft` | The material is explicitly known to be a local draft or pending delivery. |
| `reviewed` | Actual checks are documented, with their scope stated. |
| `published` | A real platform publication receipt or reference; an explicit `source-ref` is required. |

A historical folder date is a batch label unless a generation record corroborates it. Without publication evidence, file existence does not mean “published”; uncertainty also does not establish “never published.”

## Use archives for deeper reviews

Follow a cycle of **specific claim → original evidence → counterexamples or gaps → verification action → review again**. State the claim and scope, point to actual sources, identify unsupported conclusions and alternative explanations, turn questions into executable checks, then record the results and revisit the review. Keep earlier versions and the reasons a conclusion changed.

When evidence is insufficient, leave scores unrated and describe what is missing. A successful model call or valid JSON response does not mean the project passed acceptance. Archiving a recommendation does not mean it was carried out.

Original prompts are not included in model-review requests by default. If the user wants their contents considered, first select a necessary summary suitable for that reviewer. Local retention is not permission to send it elsewhere. See [Privacy](privacy.en.md) for data boundaries and the [Agent archive protocol](../skill/agent-workhub/references/project-archive.md) for execution guidance.
