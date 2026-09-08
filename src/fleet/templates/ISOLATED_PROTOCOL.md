> ## Isolation mode
> This task runs in an isolated git worktree on branch `fleet/<task_id>`, checked out at your
> working directory. When your work is complete:
> 1. Commit EVERYTHING to this branch: `git add -A && git commit -m "<clear message>"`.
> 2. Write `artifacts/RESULT.json` with `status="done"`; fleet merges your branch into the base
>    branch and closes the bead. Do NOT run `fleet bd close` yourself. Do NOT run
>    `fleet serve restart`. Do NOT touch the base branch — stay on `fleet/<task_id>`.
> 3. Exit 0. A separate validation step merges your branch (fast-forward, else `--no-ff`),
>    runs the repo's post-merge check, and closes the task. If you exit without committing,
>    your work cannot be validated.
