# Security policy

## Supported scope

There is currently no verified security-maintenance promise for a historical release range. The active development branch is the review target; users should not infer that older versions receive security fixes. Maintainers must publish an explicit supported-version table before a new release.

## Reporting

Use the repository's **Security → Report a vulnerability** private reporting flow if it is enabled. Its availability has not been verified here. If unavailable, open a minimal issue asking for a private reporting channel, without exploit details, credentials, document contents or personal paths. No unconfirmed email address is provided.

Do not attach raw logs or private documents to public issues. The built-in diagnostic ZIP uses fixed allowlists; inspect it before sharing.

## Update trust

Updates require an independently configured P-256 trust root, a valid signature over SHA256SUMS, a matching archive checksum, the GitHub asset digest, bundle identity and code-signature checks. A missing key disables installation. Never accept a public key shipped inside an untrusted update as the trust root.

Archive extraction rejects traversal, special files, case-insensitive duplicates, escaping links and writes through links, and enforces expansion limits. Native validation and rollback testing remain required release gates, not assumed guarantees.
