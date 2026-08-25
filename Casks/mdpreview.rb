cask "mdpreview" do
  version "1.4.8"
  sha256 "52be16522778840ad26bcdbec58930a8290505d5aca2d1c33383aab3850426c2"

  url "https://github.com/tahoeliu/mdPreview/releases/latest/download/mdPreview.dmg"
  name "mdPreview"
  desc "Free Markdown viewer and editor for macOS"
  homepage "https://github.com/tahoeliu/mdPreview"

  app "mdPreview.app"

  zap trash: [
    "~/Library/Application Support/mdPreview",
    "~/Library/Logs/mdPreview.log",
  ]
end
