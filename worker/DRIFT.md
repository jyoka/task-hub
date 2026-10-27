# task-hub drift report instructions (Goldfish)

A recurring goal named in `[triggers] drift_report` (docs/triggers.md) makes a research card whose Goal is the part
below the `---` line, then `## Targets` with the goal's own text: the documents and the code to hold against each
other. The agent that runs the card is a Goldfish of the Elephant-Goldfish Model: each period's card is a new Issue,
so its agent has no conversation and no earlier report, only this Goal and the repository at the card's branch.
Its report is the drift report.

This is task-hub's counterpart of the Elephant-Goldfish Model's `/egm-drift-report`:
https://github.com/google/elephant-goldfish-model (Apache License 2.0). The wording here is task-hub's own; the EGM
plugin and its AST scanner are not needed.

---

Write a drift report: find where the documents below and the code they describe disagree. You are a Goldfish, an
independent reader with no other context: you have not seen the conversations the documents and the code were
written in, earlier drift reports, or other tasks. Judge only what the documents say and what the code does, as
they are in the current directory now.

Change nothing. Every disagreement goes into the report; whether to fix it, and which side, is the human's decision.
The repository's agent instructions about tests and pull requests do not apply here: there is no change to test.

## What you read

- The documents and the code named under Targets at the end of this Goal, in this repository. A folder means every
  file in it. If Targets does not say which side a path is on, a prose file (Markdown, text) is a document and the
  rest is code.
- Other files of this repository only to follow a claim: a test that shows what the code is meant to do, a file a
  document names. They are evidence, not targets: do not look for drift in them.

## What you do not read

- Git history (`git log`, `git blame`, other branches), pull requests, Issues, the task board, and earlier drift
  reports: drift is about what the files say now, not how they got there. A Goldfish that knows the history
  explains drift away instead of reporting it.
- Anything outside the current directory: home folders, other repositories, agents' notes or memory.
- Do not run the code, its tests, or a build. Do not call GitHub (`gh`) or paid external APIs, or touch secrets
  such as `.env`.

## How to look

1. Go through the documents and list their checkable claims: commands, flags and their defaults, config keys and
   sections, file names and paths, formats, statuses and their moves, numbers (limits, intervals, counts), what
   happens on errors, and promises ("never", "only", "at most once").
2. For each claim, find the code that decides it (search for the name, the number, the message) and read it. A
   claim is drift only when you can point to the line that does something else, or show that nothing does it.
3. Also note what the code does that a document describes in the wrong place or not at all, when a reader of the
   documents would miss it: a command, a config key, a file, a status.
4. When two documents disagree with each other, report that too, with the code that settles it.

Leave out wording, style, translation, and typos that do not change the meaning. If the targets are too large to
check every claim, check the ones a user or an agent acts on first (commands, config, file formats, safety
promises) and say what you did not get to.

## Severity

Sort each item as blocking or minor, as task-hub's code review does:

- **Blocking**: someone who trusts the document (a user, a developer, an agent) would do the wrong thing or be
  hurt by it: a command, flag, key, default, or file that does not exist or behaves otherwise; a safety promise the
  code does not keep; a documented decision the code goes against.
- **Minor**: real, but nobody would act wrongly on it: an outdated number that changes nothing important, a
  feature the documents do not mention, an incomplete or imprecise description.

## The drift report

The report's Summary says how many items you found (blocking and minor) and the one or two that matter most, in
words, without file paths. Under Details, list every item, blocking first, one list item each, in this shape:

```markdown
- **blocking** <one line: what disagrees>
  - Document: `docs/file.md:12`: "the words it says"
  - Code: `path/to/code:345` `function_name`: what it does instead
  - Likely right: the code / the document / unclear, and why (the evidence: a test, another document, the
    code's own comment)
  - Fix: change the document to say ... / change the code so that ... (one proposal; more only if it is unclear)
```

Add no headings of your own: Summary and Details stay the only headings inside the Report. To group the items
(by document, say), start a group with a bold line, not a heading. Give the line numbers of the files as they are
now. When the code has nothing for a claim, write
`Code: none (searched: rg -n "..." path)`. After the list, under Details, say what you checked (which documents,
roughly how many claims) and what you did not check. If you found no drift, say so, and what you checked.

Under Please review, list the blocking items the human should look at first. For the learning route, take the
most serious item.
