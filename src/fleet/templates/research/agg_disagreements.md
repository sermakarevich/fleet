<!-- placeholders: {{target}} {{topic}} {{focus}} -->
Write the disagreements file for the research topic `{{topic}}`.

Focus (what this research must answer): `{{focus}}`.

Read ONLY `{{target}}/topics/*/digest.md` and the source summaries they
link (`{{target}}/sources/<Name>/summary.md`). Read nothing else: no wiki
pages, no raw sources, never the web.

Write `{{target}}/disagreements.md`: one section per real contradiction,
`## <claim A> vs <claim B>`, who says what with source links, the likely
reason (different setting, different metric, different date, different
incentive), and which side the evidence favours or "unresolved". Include
only real contradictions, not differences of emphasis. Zero sections is a
legitimate outcome -- when none is found, say "none found" explicitly with
the reason, rather than inventing tension.

Read only the files named above. Never fetch the web or read raw sources. Do not run git — the knowledge base syncs itself. Write $FLEET_TASK_DIR/RESULT.json as the protocol says. Do not close the bead yourself.
