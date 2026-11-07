# Local GitHub distribution policy

This repository intentionally uses ad-hoc signing, matching the author's chosen
distribution method. Developer ID and notarization are optional and are not a
prerequisite for the intended small GitHub audience.

## Current release decision: BLOCKED

No production signing key is configured. T27 signed ZIP installation fails closed. T28 Quick Look is skipped at its native installation gate. T32 large native module migration is blocked by unavailable Python/native regression. No universal2 compatibility is claimed.

### Required evidence

- [ ] Independently verify and configure the P-256 production public key; never commit its private key.
- [ ] Pass signature-valid/tampered/wrong-key tests through the production verifier and hostile ZIP extraction tests.
- [ ] Pass output quality and actual WebKit performance budgets; record native cold start.
- [ ] Run `scripts/verify-headless.py --app …` against the built app (hidden-window export of every format, multi-page PDF with bookmarks and page numbers, existing output refused).
- [ ] Check every bundled Mach-O executable/library/extension before claiming architecture support.
- [ ] Verify rollback, fresh-account installation and all compatibility cells below.
- [ ] Provide actual version-specific CHANGELOG notes, complete licences and Credits.
- [ ] Confirm the GitHub Actions workflows (`ci.yml`, `release.yml`) are green on the release commit.
- [ ] Configure reporting contacts and any Homebrew tap only with explicit maintainer approval.

### Manual compatibility matrix

All cells are **NOT TESTED for the current increment**; missing evidence blocks release.

| Format | Targets | Result |
|---|---|---|
| PDF | Preview, Safari, Chrome, Acrobat, iOS Files, WeChat, physical A4 | NOT TESTED |
| Word | Word Mac/Windows, Pages, WPS, Google Docs, LibreOffice, Feishu, DingTalk | NOT TESTED |
| HTML | Safari, Chrome, Edge Windows, mobile, dark mode | NOT TESTED |
| PNG | WeChat compressed transfer, iPhone Photos | NOT TESTED |
| Rich text | WeChat, Feishu, DingTalk, Outlook, Gmail, Word, Notion, Notes | NOT TESTED |
| Install | fresh accounts; CLI/Homebrew/DMG; macOS 13/14/15/26; arm64/Intel/Rosetta | NOT TESTED |

### Human-only promotion after approval

Review GitHub topics, awesome-mac PR, Hacker News Show HN, Reddit r/macapps, V2EX, 少数派, 即刻 and Product Hunt. Do not post automatically. No sponsorship identity or unconfirmed contact is supplied.

## Evidence input contract

`verify-all.sh` requires all four inputs: `MDPREVIEW_VERIFY_APP` (an explicitly selected candidate bundle), `MDPREVIEW_VERIFY_ARCH` (`arm64`, `x86_64` or independently validated `universal`), `MDPREVIEW_COMPAT_MATRIX` (JSON), and `MDPREVIEW_COLD_START_RESULT` (JSON). Missing inputs fail; there is no green skip or automatic installation.

Matrix `metadata` must contain `version` matching VERSION, `bundleSha256` calculated by the exported `bundleDigest(app)` in `scripts/verify-matrix.mjs`, and `reviewer`. Every target enumerated in that script must contain `status: "passed"`, nonempty `environment`, a non-future ISO `verifiedAt`, a PNG/JPEG `evidence` path relative to the matrix JSON and its `sha256`. The additional `headless` targets require observations of hidden-window behavior, zero network requests, timeout/no-late-write and exit codes. Hash matching does not establish screenshot truth: the reviewer must inspect the evidence. Do not fill missing cells with synthetic passes.

Cold-start JSON must contain `kind: "native-process-first-screen"`, positive `milliseconds` below 1500, matching `version` and `bundleSha256`, nonempty `environment` and a non-future ISO `measuredAt`. Browser page timings cannot substitute for native startup.

The local `scripts/get.sh` delegates to the audited source checkout and its single embedded Python trust root; it is not a standalone curl bootstrap. The production key remains empty. Initial signed installation now performs a PID/version-bound isolated startup probe before retaining the new installation; that implementation, rollback and ZIP attack tests have **not** been run in the restricted environment. No quarantine-clearing command is used.

## Candidate gates

Run `./verify-all.sh` in an ordinary Mac Terminal. It fails if any enabled gate
fails, and does not install over /Applications. Tests isolate configuration,
drafts and logs. A unit-test pass does not imply a native/UI gate passed.

1. Install Python 3.13, create .venv, install requirements-lock.txt, and run npm ci.
2. Run npx playwright install chromium webkit (set PLAYWRIGHT_BROWSERS_PATH to WorkSpace/browsers to keep it out of your home directory).
3. Run all regression, failure injection and Chromium/WebKit tests.
4. Build the application and DMG, verify vendored checksums, packaged resources,
   code signature, app version and ATS configuration.
5. Run native WKWebView verification: Unicode save, shell code preservation,
   current-source HTML export, native PDF and normal process quit.
6. Record OS and architecture. macOS 13 is the declared minimum; Intel and older
   supported macOS installations need their own verification before claiming support.

## Assets and update checks

Products are under WorkSpace/dist/release-VERSION. New updates require an architecture-labelled signed ZIP plus SHA256SUMS and SHA256SUMS.sig, bound to an exact version. The legacy DMG download path is disabled. Existing Cask release metadata remains unchanged. scripts/sign-release.mjs signs only supplied artifacts with a supplied matching private key; it never generates a production key or publishes.

The updater requires GitHub's asset size and SHA-256 digest, a matching release
version/bundle ID and a valid code signature (ad-hoc allowed). A configured Team
ID additionally enables publisher/notarization checks. Missing signatures, trust roots or digests disable signed installation; they never fall back to unsigned installation. Installation
waits for the old process to exit and restores the prior application if the new
application never acknowledges its UI readiness.

No script automatically uploads assets, pushes Git, or publishes a release.

## History

The original WorkSpace, outputs, application backups and Git history were copied
and retained. `scripts/backup-inventory.py` inventories them without deleting
anything. Future retention decisions should preserve tagged releases and at
least one restorable working app; build caches can be regenerated separately.
