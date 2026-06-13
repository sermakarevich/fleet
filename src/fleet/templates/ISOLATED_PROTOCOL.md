> ## Isolation mode
> This task runs in an isolated git worktree on branch `fleet/<task_id>`, checked out at your
> working directory. When your work is complete:
> 1. Commit EVERYTHING to this branch: `git add -A && git commit -m \"<clear message>\"`.
> 2. Do NOT run `bd close`. Do NOT run `fleet serve restart`. Do NOT touch `main`.
> 3. Exit 0. A separate validation step merges your branch into `main`, rebuilds the UI, and
>    closes the task. If you exit without committing, your work cannot be validated.
