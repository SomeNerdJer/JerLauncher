# Run once per clone (Windows) so commits push as SomeNerdJer.
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
git -C $Root config user.name "SomeNerdJer"
git -C $Root config user.email "SomeNerdJer@users.noreply.github.com"
git -C $Root config core.hooksPath .githooks
Write-Host "Git identity set to SomeNerdJer for this repo."
