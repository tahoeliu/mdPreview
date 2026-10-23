cask "mdpreview" do
  version "1.4.11"
  sha256 "386e75ada70f6a04cdd4953e75abb9c4196c90aeae4ae2d4475f085953195203"

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
