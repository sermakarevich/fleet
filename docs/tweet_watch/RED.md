# tweet_watch — red run (autocode step 7/11)

Date: 2026-09-26. Branch: `autocode/tweet_watch`.
Scaffold state: every function in `src/fleet/tweet_watch/` (`worker.py`,
`kb_files.py`, `x_fetch.py`, `reply_files.py`) raises `NotImplementedError`;
only constants (`SEED_HANDLES`, KB paths, `Tweet`, `FetchError`) and
signatures exist. No worker code yet — new tests are expected to fail.

## Old suite (must stay green, must match BASELINE.md)

- Command: `uv run pytest -q -p no:cacheprovider tests --ignore=tests/integration --ignore=tests/tweet_watch`
- Result: **2395 passed, 0 failed** — matches `BASELINE.md` exactly
  (`2395 passed`, no pre-existing failures). Scaffold broke nothing.
- Note: the step's literal command (`tests --ignore=tests/integration`,
  without excluding `tests/tweet_watch`) collects the new tests too:
  `410 failed, 2422 passed, 53 errors` — i.e. 2395 old passes + 27 new
  passes listed below, plus the 463 red new tests. The old 2395 all pass.

## New tests (must be red)

- Command: `uv run pytest tests/tweet_watch -q`
- Result: **410 failed, 27 passed, 53 errors** (490 collected).
- Red is genuine: failures are assertion failures and fixture errors
  against the `NotImplementedError` scaffold, not collection breakage.
  (Sibling tests that guard with
  `assert not isinstance(excinfo.value, NotImplementedError)` correctly
  fail; only the tests below slip through.)

## Suspicious list: 27 new tests that already pass on the empty scaffold

None of these execute any unimplemented worker logic. No test was edited.

- `m1/test_read_watchlist.py::test_seed_handles_are_the_five_spec_handles_in_order`
  — asserts only the `SEED_HANDLES` scaffold constant; calls no function.
- `m2/test_happy_path.py::test_seam_defaults`
  — inspects the `fetch_tweets` signature defaults via `inspect`; calls nothing.
- `r3/test_score_interests_contract.py::test_f4_empty_interests_aborts`
- `r3/test_score_interests_contract.py::test_f4_whitespace_interests_aborts`
- `r3/test_score_interests_contract.py::test_f4_voice_notes_only_aborts`
- `r3/test_score_interests_contract.py::test_f4_abort_is_not_silent_low`
  — all four use bare `pytest.raises(Exception)`, which the scaffold's
  `NotImplementedError` satisfies. Vacuous until the real abort lands.
- `r6/test_persist_gate.py::test_f8_zero_high_tweets_means_zero_proposals_zero_files`
  — asserts an empty tmp dir is empty; calls no worker code.
- `r9/test_install_args.py` (15 tests: `test_install_names_exact_schedule_name`,
  `test_variant_name_is_a_mismatch`, `test_install_uses_exact_cron`,
  `test_cron_has_five_fields`, `test_expected_cron_parses`,
  `test_wrong_cron_is_a_mismatch`, `test_truncated_cron_is_rejected_by_parser`,
  `test_install_uses_overlap_skip`, `test_missing_or_queue_overlap_is_a_mismatch`,
  `test_install_uses_opencode_coder`, `test_wrong_coder_is_a_mismatch`,
  `test_create_command_quotes_cron_with_single_quotes`,
  `test_create_command_pins_every_flag`, `test_fleet_cli_is_the_install_path`,
  `test_schedule_cwd_is_the_fleet_repo_checkout`)
- `r9/test_install_state.py` (4 tests: `test_install_goes_through_fleet_schedule_machinery`,
  `test_no_off_fleet_scheduler_substitute`, `test_create_alone_is_unverified`,
  `test_retry_uses_the_identical_spec`)
- `r9/test_verify_concurrency.py::test_installed_overlap_skip_sheds_colliding_runs`
  — all 20 exercise the test conftest constants and the pre-existing
  fleet schedule machinery (`fleet.schedules`, `fleet.cli.schedule`),
  never the tweet_watch worker. They pin the install contract, which is
  fine, but they are green before any worker code exists.

## Verdict

Starting point confirmed: old suite green (2395 passed, matches baseline),
new tests red (410 failed + 53 errors, 27 vacuously green as listed).
Ready for implementation steps. No test changes requested or made.
