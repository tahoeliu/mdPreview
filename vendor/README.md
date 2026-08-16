# Vendored frontend libraries

These files are checked into the repo root (no npm build step). Recorded here
for provenance and future upgrades. Verify a replacement matches the recorded
SHA-256 before committing.

| File | Source | Version | SHA-256 |
|---|---|---|---|
| marked.min.js | https://github.com/markedjs/marked | v12.0.0 | eb1f6b19880bc80a5fe34c6a61885173b60edda455ba7a33c98714db17d39f99 |
| mermaid.min.js | https://github.com/mermaid-js/mermaid | 11.16.0 | 74d7c46dabca328c2294733910a8aa1ed0c37451776e8d5295da38a2b758fb9b |
| turndown.js | https://github.com/mixmark-io/turndown | (bundled build) | ae3605eb07ab920a2d181008ace692ec560fa6cd67d2e291f77cbc5c4322cd38 |
| html-docx-js.js | https://www.npmjs.com/package/html-docx-js | 0.3.1 | (see sha256 below) |
| html2canvas.min.js | https://html2canvas.hertzen.com | 1.4.1 | (see sha256 below) |

Upgrade checklist:
1. Download the new release build of the library.
2. Compare/update the SHA-256 here.
3. Run the full JS test suites (regression + security + performance) and the
   real-app smoke test; watch for mermaid theme/security regressions in
   particular.
