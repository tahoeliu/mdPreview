# Local GitHub distribution policy

This repository intentionally uses ad-hoc signing, matching the author's chosen
distribution method. Developer ID and notarization are optional and are not a
prerequisite for the intended small GitHub audience.

## Candidate gates

Run `./verify-all.sh` in an ordinary Mac Terminal. It fails if any enabled gate
fails, and does not install over /Applications. Tests isolate configuration,
drafts and logs. A unit-test pass does not imply a native/UI gate passed.

1. Install Python 3.13, create .venv, install requirements-lock.txt, and run npm ci.
2. Set PLAYWRIGHT_BROWSERS_PATH to WorkSpace/browsers and run npx playwright install chromium webkit.
3. Run all regression, failure injection and Chromium/WebKit tests.
4. Build the application and DMG, verify vendored checksums, packaged resources,
   code signature, app version and ATS configuration.
5. Run native WKWebView verification: Unicode save, shell code preservation,
   current-source HTML export, native PDF and normal process quit.
6. Record OS and architecture. macOS 13 is the declared minimum; Intel and older
   supported macOS installations need their own verification before claiming support.

## Assets and update checks

Products are under WorkSpace/dist/release-VERSION. The canonical update asset is
mdPreview.dmg, bound to a specific `vVERSION` GitHub release. After building it,
run `.venv/bin/python scripts/prepare-release.py` to update the cask using the
actual SHA-256. The cask stays on the previous public release until this step.

The updater requires GitHub's asset size and SHA-256 digest, a matching release
version/bundle ID and a valid code signature (ad-hoc allowed). A configured Team
ID additionally enables publisher/notarization checks. Missing digests cause a
safe manual-install fallback; they are never silently trusted. Installation
waits for the old process to exit and restores the prior application if the new
application never acknowledges its UI readiness.

No script automatically uploads assets, pushes Git, or publishes a release.

## History

The original WorkSpace, outputs, application backups and Git history were copied
and retained. `scripts/backup-inventory.py` inventories them without deleting
anything. Future retention decisions should preserve tagged releases and at
least one restorable working app; build caches can be regenerated separately.
