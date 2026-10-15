#!/usr/bin/env bash
# Write a new version and sha256 into a cask in wesleyel/homebrew-tap and push it.
# usage: update-tap-cask.sh CASK VERSION SHA256SUMS_FILE
# Needs GH_TOKEN with contents:write on wesleyel/homebrew-tap.
set -euo pipefail

cask=$1
version=$2
sums=$3
sha=$(awk 'NR == 1 { print $1 }' "$sums")
[[ $sha =~ ^[0-9a-f]{64}$ ]] || { echo "::error::no sha256 in $sums"; exit 1; }

dir=$(mktemp -d)
git clone --quiet --depth 1 "https://x-access-token:${GH_TOKEN}@github.com/wesleyel/homebrew-tap.git" "$dir"
file="$dir/Casks/$cask.rb"
sed -i.bak -E \
  -e "s/^  version \"[^\"]*\"/  version \"$version\"/" \
  -e "s/^  sha256 \"[0-9a-f]{64}\"/  sha256 \"$sha\"/" "$file"
rm -f "$file.bak"

cd "$dir"
if git diff --quiet; then
  echo "$cask is already at $version ($sha)"
  exit 0
fi
git -c user.name="github-actions[bot]" \
    -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
    commit --quiet -am "$cask $version"
# Both dictionary workflows may push at once: rebase and retry.
for _ in 1 2 3; do
  git push --quiet origin HEAD:main && { echo "pushed $cask $version"; exit 0; }
  git pull --quiet --rebase origin main
done
echo "::error::could not push $cask"
exit 1
