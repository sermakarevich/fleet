> ## Isolation mode
> This task runs in an isolated git worktree on branch `fleet/<task_id>`, checked out at your
> working directory. When your work is complete:
> 1. If you changed files in this repo, commit ALL of them to this branch:
>    `git add -A && git commit -m "<clear message>"`. If the task changed nothing in this
>    repo (research, notes elsewhere), skip this step: no commit is required.
> 2. Write `artifacts/RESULT.json` with `status="done"`; fleet merges your branch into the base
>    branch and closes the bead. Do NOT run `fleet bd close` yourself. Do NOT run
>    `fleet serve restart`. Do NOT touch the base branch — stay on `fleet/<task_id>`.
> 3. Exit 0. A separate validation step merges your branch (fast-forward, else `--no-ff`),
>    runs the repo's post-merge check, and closes the task. A branch with no commits simply
>    closes. Uncommitted changes left behind cannot be validated and you will be asked again.
