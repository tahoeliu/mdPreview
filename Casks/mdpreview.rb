cask "mdpreview" do
  version "1.3.1"
  sha256 :no_check

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
