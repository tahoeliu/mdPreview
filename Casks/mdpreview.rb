cask "mdpreview" do
  version "1.4.9"
  sha256 "929530c19d10b8a40fcd42693bbd6c2847aa550201e065d6f1db9167b727a683"

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
