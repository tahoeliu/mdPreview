# mdPreview development workflow

Source, resources, tests (`tests/`), CI (`.github/`) and developer docs are committed.
`WorkSpace/` and `outputs/` are git-ignored scratch space: build products, caches, logs, probe PDFs and local evidence only.

- Use Python 3.13 and Node 22+; install `requirements/lock.txt`, `requirements/dev.txt` and run `npm ci --ignore-scripts`.
- Run `npm test`, `.venv/bin/python scripts/test-python.py`, `npm run test:e2e`. Tests isolate app data via `MDPREVIEW_DATA_DIR`.
- Build with `scripts/build.sh` or `scripts/build_dmg.sh`; outputs default to `WorkSpace/build` and `WorkSpace/dist`.
- Verify a built app with `scripts/verify-headless.py --app …` (real hidden-window export of every format) and `scripts/verify-native.py`.
- Build roots get Spotlight exclusion markers before producing application bundles.
- Do not replace `/Applications` during development tests.
- Distribution policy: ad-hoc code signature, GitHub Releases, plus our own ECDSA release signature (the public key is pinned in `mdpreview_core/release_sig.py`). Apple Developer ID / notarization are not used.
- Never claim an architecture or OS version works unless it was actually tested.
- Updates require a signed `SHA256SUMS`, the matching archive digest and the GitHub asset digest, and roll back on failure.
