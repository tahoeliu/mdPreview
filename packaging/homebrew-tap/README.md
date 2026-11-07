# Homebrew tap for mdPreview

This folder describes how to publish the Homebrew tap. The tap itself lives in its own repository because Homebrew requires the name `homebrew-<tap>`.

## One-time setup (maintainer)

1. Create an empty public repository `tahoeliu/homebrew-tap` on GitHub.
2. Create a fine-grained personal access token limited to that repository with **Contents: Read and write**.
3. In the main repository add it as the Actions secret `HOMEBREW_TAP_TOKEN`.

From then on `release.yml` regenerates `Casks/mdpreview.rb` from the signed `SHA256SUMS` on every tag and pushes it to the tap. Without the secret the step is skipped and the release still succeeds.

## Generate the cask by hand

```bash
python scripts/prepare-release.py cask --sums path/to/SHA256SUMS --out ../homebrew-tap/Casks/mdpreview.rb
```

## Users

```bash
brew install --cask --no-quarantine tahoeliu/tap/mdpreview
```

`--no-quarantine` avoids the first-launch Gatekeeper prompt for the ad-hoc signed app. Without it, use System Settings > Privacy & Security > **Open Anyway**.
