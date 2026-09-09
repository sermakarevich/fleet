Branch `{branch}` in `{repo_root}` no longer merges into `{base_ref}` cleanly.
Conflicting files: {files}.

Steps:
(1) `git worktree add` a temp dir under $FLEET_HOME/worktrees on `{branch}`;
(2) `git merge {base_ref}`;
(3) resolve each conflict keeping BOTH sides' intent — the branch is the newer work,
`{base_ref}` may hold partial auto-commits of the same files; never resolve by discarding
one side wholesale without saying why in the commit message;
(4) run the project's checks (`just check` if a justfile has it, else the tests you can find);
(5) `git commit` the merge;
(6) in `{repo_root}`: `git merge --ff-only {branch}` then `git push`;
(7) remove the temp worktree, `git branch -d {branch}`;
(8) `fleet bd close {task_id} --reason "..."`, then close your own task.
Never touch uncommitted files in `{repo_root}`; never `git add -A`.
