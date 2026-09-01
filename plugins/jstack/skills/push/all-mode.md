# `all` mode

Scope widens to every pending change in each repo; grouping, subject vocabulary and trailers stay the same contract.

Resolve repos as in step 1. If the session touched no repo but the cwd is itself one, use that.

```bash
git -C "$R" status --short
git -C "$R" diff --stat HEAD
```

One extra grouping rule applies here only — **same author trail**: where another session or process clearly touched a file, preserve that grouping rather than merging it into yours.

Write the plan back to the user before committing anything:

```
push plan:
  <repo-a> (N commits):
    1. <type>(<scope>): <subject> — <file count> files
    2. ...
  <repo-b> (M commits):
    1. ...
```

Execute each commit in order with the same `-C "$R"` HEREDOC pattern. Push once per repo after its commits land, unless arg `0`.

Report per repo: `<N> commits, <sha-first>..<sha-last> on <branch> in <repo-name>`. Then stop.
