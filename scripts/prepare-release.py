"""从已签名的 SHA256SUMS 生成 Homebrew Cask；不联网、不发布。

用法：
  python scripts/prepare-release.py cask --sums dist/SHA256SUMS --out packaging/homebrew-tap/Casks/mdpreview.rb
  python scripts/prepare-release.py notes --version 2.0.0          # 打印 CHANGELOG 中该版本的说明

两个架构的 ZIP 都必须出现在清单里，哈希直接取自（已被我们的发布密钥签名的）清单，
所以 Cask 与 Release 资产不会各说各话。
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CASK = '''cask "mdpreview" do
  arch arm: "arm64", intel: "x86_64"

  version "{version}"
  sha256 arm:   "{arm64}",
         intel: "{x86_64}"

  url "https://github.com/tahoeliu/mdPreview/releases/download/v#{{version}}/mdPreview-#{{version}}-#{{arch}}.zip"
  name "mdPreview"
  desc "Free Markdown viewer and editor"
  homepage "https://github.com/tahoeliu/mdPreview"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on macos: ">= :ventura"

  app "mdPreview.app"

  zap trash: [
    "~/Library/Application Support/mdPreview",
    "~/Library/Logs/mdPreview",
    "~/Library/Preferences/tahoeliu.mdpreview.plist",
    "~/Library/Saved Application State/tahoeliu.mdpreview.savedState",
  ]

  caveats <<~EOS
    mdPreview is open source and ad-hoc signed (no paid Apple Developer certificate).
    Install with --no-quarantine to avoid the first-launch Gatekeeper prompt:

      brew install --cask --no-quarantine tahoeliu/tap/mdpreview

    If macOS still blocks it: System Settings > Privacy & Security > "Open Anyway".
  EOS
end
'''


def parse_sums(text):
    entries = {}
    for line in text.splitlines():
        match = re.fullmatch(r'([a-f0-9]{64}) [ *]([A-Za-z0-9][A-Za-z0-9._-]*)', line)
        if not match or match[2] in entries:
            raise ValueError('invalid checksum manifest line: ' + line[:80])
        entries[match[2]] = match[1]
    return entries


def render_cask(sums_text, version=None):
    entries = parse_sums(sums_text)
    found = {}
    for name, digest in entries.items():
        match = re.fullmatch(r'mdPreview-(\d+\.\d+\.\d+(?:\.\d+)?)-(arm64|x86_64)\.zip', name)
        if match:
            found.setdefault(match[1], {})[match[2]] = digest
    versions = sorted(found)
    if len(versions) != 1:
        raise ValueError(f'expected ZIP assets for exactly one version, found {versions}')
    release = versions[0]
    if version and version != release:
        raise ValueError(f'manifest is for {release}, expected {version}')
    missing = [arch for arch in ('arm64', 'x86_64') if arch not in found[release]]
    if missing:
        raise ValueError('manifest lacks ZIP for: ' + ', '.join(missing))
    return CASK.format(version=release, arm64=found[release]['arm64'], x86_64=found[release]['x86_64'])


def release_notes(changelog_text, version):
    pattern = re.compile(r'^## \[?' + re.escape(version) + r'\]?(?:\s.*)?$', re.M)
    match = pattern.search(changelog_text)
    if not match:
        raise ValueError(f'CHANGELOG has no section for {version}')
    rest = changelog_text[match.end():]
    following = re.search(r'^## ', rest, re.M)
    body = (rest[:following.start()] if following else rest).strip()
    if not body:
        raise ValueError(f'CHANGELOG section for {version} is empty')
    return body + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    cask = sub.add_parser('cask')
    cask.add_argument('--sums', required=True)
    cask.add_argument('--out', required=True)
    cask.add_argument('--version')
    notes = sub.add_parser('notes')
    notes.add_argument('--version', required=True)
    notes.add_argument('--changelog', default=str(ROOT / 'CHANGELOG.md'))
    args = parser.parse_args(argv)
    try:
        if args.command == 'cask':
            text = render_cask(Path(args.sums).read_text(encoding='utf-8'), args.version)
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding='utf-8')
            print('wrote', out)
        else:
            sys.stdout.write(release_notes(Path(args.changelog).read_text(encoding='utf-8'), args.version))
    except (ValueError, OSError) as error:
        print('prepare-release:', error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
