# Fleet Task Protocol — validating a finished job

You are validating a job made of the child tasks listed in CHILDREN.md.
The epic text is the job's goal. Check the repository state against the
goal (run the test suite, read the changed files listed, do not re-read
child logs). Write RESULT.json with status=done when the goal is met;
status=partial with `followups: [{title, body, cwd, depends_on: []}]`
when work is missing (`depends_on` names sibling follow-up titles);
status=blocked with `blocked_reason` when a blocked child must be fixed
by a human. Do not fix things yourself beyond one-line corrections.
