# Releasing mdPreview

Distribution is GitHub Releases with an **ad-hoc code signature** (no Apple Developer ID, no notarization) plus our own **ECDSA release signature** over `SHA256SUMS`. The pinned public key (`mdpreview_core/release_sig.py`, also `scripts/get.sh` and `scripts/release-pubkey.pem`) is what protects the install and update path; its fingerprint is published in [SECURITY.md](SECURITY.md).

## One-time setup

1. **Signing key.** It already exists at `~/.mdpreview-release/release-key.pem` (P-256, mode 0600) with its public half pinned in the repository. **Back it up somewhere safe and private** — if it is lost, existing installs can never be updated automatically again, because they only trust this key. Never commit it.
2. **GitHub Actions secrets** (Settings → Secrets and variables → Actions):
   - `RELEASE_SIGNING_KEY` — the full contents of `release-key.pem`. Used only by the `publish` job of `release.yml`.
   - `HOMEBREW_TAP_TOKEN` — optional; a fine-grained token with *Contents: read and write* on `tahoeliu/homebrew-tap`. See `packaging/homebrew-tap/README.md`.
3. **Repository settings:** enable *Private vulnerability reporting* (referenced by SECURITY.md), enable GitHub Pages from `/docs`, and add topics (`markdown`, `macos`, `markdown-viewer`, `pdf`).
4. **Homebrew tap (optional):** create the empty public repository `tahoeliu/homebrew-tap`. Until it exists, remove the Homebrew lines from the README or the first `brew install` will fail.

## Cutting a release

1. Bump the version in `VERSION`, `Info.plist` (both keys) and `package.json`/`package-lock.json`; write the section `## [X.Y.Z] - date` in `CHANGELOG.md` (the release notes are extracted from it).
2. Build and verify locally on an Apple Silicon Mac:
   ```bash
   ./build_dmg.sh
   MDPREVIEW_VERIFY_APP="$PWD/WorkSpace/dist/release-$(cat VERSION)/mdPreview.app" MDPREVIEW_VERIFY_ARCH=arm64 ./verify-all.sh
   ```
   It runs the static and supply-chain checks, every test suite, the native acceptance scripts (headless export of all formats, native self-test, the signed-update pipeline on the real bundle), the cold-start measurement, and the performance and accessibility budgets. It never installs or publishes.
3. Commit, then tag with exactly `v` + the contents of `VERSION` and push the tag:
   ```bash
   git tag "v$(cat VERSION)" && git push origin "v$(cat VERSION)"
   ```
4. `release.yml` builds arm64 (`macos-14`) and x86_64 (`macos-15-intel`) natively, runs the native acceptance on each, packages `mdPreview-<version>-<arch>.zip` and `.dmg`, signs `SHA256SUMS` in a separate job that holds the only write permission, re-verifies the signature against the published key, creates the GitHub release and (if configured) updates the Homebrew tap.
5. After it finishes, install the published release on a clean user account with the one-line installer and open a document. `mdPreview.dmg` (arm64) is also attached because releases up to 1.5.0 look for that asset name.

## What is and is not verified

| Area | Verified automatically | Not independently verified |
|---|---|---|
| Output (print, PDF, Word, HTML, PNG, TXT, rich text) | Native acceptance on the built app: pagination, page numbers, bookmarks, searchable Chinese text, Word heading styles/tables/footnotes (also parsed by macOS `textutil`), self-contained HTML, no leaked dark theme | Opening the files in Word (Mac/Windows), Pages, WPS, Google Docs, LibreOffice, Feishu, DingTalk, WeChat; pasting rich text into specific apps |
| Install / update | Installer and updater against real archives with a real key: tamper, wrong key, wrong bundle, downgrade, size limits; byte-identical staged app | A fresh-account run of the published release; macOS 13/14/15 (development is on macOS 26); Intel hardware (CI builds and smoke-tests on an Intel runner) |
| Performance | WebKit budgets on realistic documents (1 MB < 1.5 s), cold start (median of 5, budget 1.5 s) | Very low-end hardware |
| Accessibility | axe (serious/critical) in light and dark for reading, settings, find, empty and source views | Manual VoiceOver passes |
| Quick Look | The preview page in Chromium and WebKit | macOS launching the extension (see `quicklook/README.md`); not shipped |

If you do verify cross-app compatibility by hand, record it in a JSON matrix (see `scripts/verify-matrix.mjs` for the schema: every target needs `status: "passed"`, an environment, a timestamp and an evidence screenshot hash) and pass it as `MDPREVIEW_COMPAT_MATRIX`; `verify-all.sh` then validates it. Without it the script says so explicitly.

## Promotion (manual)

GitHub topics, an awesome-mac pull request, Show HN, r/macapps, V2EX, 少数派, 即刻 and Product Hunt. Do not post automatically.

## If something goes wrong

- **A bad release is published:** delete the GitHub release and tag (updates only ever see the latest non-draft, non-prerelease release), fix, and publish a higher version. Do not re-use a version number.
- **The signing key is compromised:** generate a new key, publish a release signed with the *old* key whose `release_sig.py` pins the new key (so existing installs can migrate), announce it in SECURITY.md and the release notes, then retire the old key.
