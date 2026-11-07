# Contributing

Use Python 3.13 and Node 22 or newer. Read WORKFLOW.md before changing integration points. Install locked dependencies only in an authorized development environment; do not bypass failed security or package hooks.

Tests, local workflows, fixtures, compatibility evidence and Credits.rtf belong in WorkSpace. This directory is ignored: a clean clone needs separately supplied local test resources. WorkSpace workflow templates do not run automatically on GitHub.

## Change process

1. Read the relevant OPTIMIZATION_PLAN task and existing code.
2. Add a regression test in WorkSpace/tests and establish the failing behavior.
3. Implement and wire the feature into menus, frontend, native API and packaging.
4. Run targeted JavaScript checks, the application regression suite, then required Python/browser/native gates where authorized.
5. Record actual results and blockers. Never represent an unexecuted gate as passed.
6. Make separate ordinary commits only when authorized; never remove locks or bypass hooks to force a commit.

Run `node --check app.js`, the applicable `node WorkSpace/tests/test_*.js` tests, and `bash verify-all.sh` for release verification. The release verifier deliberately fails when required evidence, tests, signing configuration or architecture checks are missing. Do not run it in an environment where its Python or build steps are prohibited.

Do not edit installed applications during development. Do not touch another session's docs changes. Keep private keys, document bodies, paths, tokens and private diagnostics out of commits. Large module migrations require per-module regression and native packaging acceptance.
