# Security policy

## Supported versions

Only the **latest release** receives security fixes. Please update (Settings → automatic update checks, or re-run the installer) before reporting.

## Reporting a vulnerability

Please report privately: open the repository's **Security → Report a vulnerability** (GitHub private vulnerability reporting). If that is not available, open a minimal public issue that only asks for a private channel — **no exploit details, credentials, document contents or personal paths**.

Never attach raw logs or private documents to public issues. The built-in diagnostic archive (Help → Export Diagnostics…) contains allow-listed settings and structured events only; inspect it before sharing.

## Release signing key

Releases are signed with an ECDSA P-256 key. The public key is pinned in `mdpreview_core/release_sig.py` and embedded in `scripts/get.sh` (also as `scripts/release-pubkey.pem`). Its SHA-256 fingerprint (of the DER-encoded SubjectPublicKeyInfo) is:

```
ab36c7ec2c07f7c5e29d127e7fd95e88d6dffa8b66c5b8317c42ab45a5886f1b
```

Verify it yourself:

```bash
curl -fsSL https://raw.githubusercontent.com/tahoeliu/mdPreview/main/scripts/release-pubkey.pem | openssl pkey -pubin -outform DER | shasum -a 256
```

The installer prints the first 16 hex characters of this fingerprint during installation. If a release ever needs to be revoked or the key rotated, it will be announced here and in the release notes.

## How updates are trusted

An update is installed only if **all** of these hold:

1. `SHA256SUMS` carries a valid signature from the pinned key above;
2. the archive's SHA-256 matches the signed list and the digest GitHub publishes for the asset;
3. the extracted bundle has the expected identifier and version and a valid code signature;
4. the archive passes extraction limits (no path traversal, special files, case-insensitive duplicates, escaping or chained symlinks, or oversized expansion).

Any failure aborts the update and leaves the installed app untouched; installation keeps a recoverable previous version until the new one starts.

mdPreview is distributed with an **ad-hoc code signature and without Apple notarization**. That is why the signature above, not macOS Gatekeeper, is what protects the update path.

## Hardening in the app

- All rendered content passes DOMPurify; URLs are filtered; the page runs under a strict Content-Security-Policy without inline scripts or `eval`.
- Remote images are not loaded unless you allow it; the app makes no other network requests besides the optional update check.
- Dependencies are pinned and checksummed (`vendor/manifest.json`); CI runs `npm audit` at the `high` level.

## Known, accepted advisories

| Component | Advisory | Why accepted |
|---|---|---|
| KaTeX 0.16.x bundled *inside* Mermaid | prototype pollution can bypass trust restrictions (low) | Fixed only in Mermaid 12 (a major upgrade we have not taken); exploitable only when the `trust` option is enabled, and Mermaid runs with `securityLevel: 'strict'` |

This table is regenerated from `npm audit` at each release.
