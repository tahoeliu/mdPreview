cask "mdpreview" do
  version "1.4.10"
  sha256 "787c5effe9e606d7c0202f3c30d3a106b0b84243854e4de8fc2b411d3670157d"

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
