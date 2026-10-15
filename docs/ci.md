# CI and releases

Two workflows: `build.yml` for the plain dictionary, `audio.yml` for the variant
with bundled pronunciation. The split by runner exists because macOS minutes
cost 10x: only the DDK compile actually needs macOS, so the 84k-entry conversion
runs on Linux.

| Job | Runner | Trigger | Does |
|---|---|---|---|
| `check` | ubuntu | every push and PR | fixture smoke test, no download |
| `smoke` | macos | push to `main`, manual | same fixture, compiled with the real DDK |
| `convert` | ubuntu | manual | download + verify upstream, JSONL → XML |
| `package` | macos | after `convert` | compile, verify bundle, zip, checksum |
| `publish` | ubuntu | manual, `publish: true` | GitHub release + SHA256SUMS, then updates the tap cask |

## Running a build

Actions → **build** → Run workflow:

| Input | |
|---|---|
| `source_tag` | upstream release tag, default `v2.0` |
| `limit` | entry cap for trial builds, `0` = all |
| `publish` | create the GitHub release and update the tap cask |

Start with `limit: 500, publish: false` after any converter change.

## Details worth knowing

**No Apple ID needed.** `package` checks out the
[nanoskript/dictionary-development-kit](https://github.com/nanoskript/dictionary-development-kit)
mirror, whose binaries are universal, so the arm64 runner needs no Rosetta step.
Nothing from the DDK reaches the published artifact — see [LICENSE-DATA.md](../LICENSE-DATA.md).

**Upstream artifact is cached** by `actions/cache` keyed on `source_tag`, so
re-runs skip the 97 MB download. The checksum from the upstream `SHA256SUMS.txt`
is verified on every fresh download.

**`package` has `timeout-minutes: 240`.** The DDK is single-threaded and the
full corpus is large; this is headroom, not an estimate.

**`publish` writes the GitHub release, then the cask.** After uploading the zip
and `SHA256SUMS.txt`, it runs `scripts/update-tap-cask.sh`, which sets `version`
and `sha256` in the cask in [wesleyel/homebrew-tap](https://github.com/wesleyel/homebrew-tap)
and pushes to its `main`. That step needs the `HOMEBREW_TAP_GITHUB_TOKEN` secret
(fine-grained, contents write on the tap). Every job other than `publish` stays
read-only.

## The audio workflow

`.github/workflows/audio.yml`, **manual trigger only** — a cold run fetches
~110k clips and takes hours, which no push should do.

| Job | Runner | Does |
|---|---|---|
| `audio` | ubuntu | download upstream, fetch clips, convert with the manifest |
| `package` | macos | stage `OtherResources`, compile, verify clips landed, zip |
| `publish` | ubuntu | upload the second asset + `SHA256SUMS-audio.txt` |

| Input | |
|---|---|
| `source_tag` | upstream release tag |
| `accents` | `uk,us` (default), or one of them |
| `limit` | headword cap for trial runs, `0` = all |
| `publish` | create the release asset and update the tap cask |

Start with `limit: 200, publish: false`.

**The clip cache is what makes a re-run survivable.** `actions/cache` keyed on
tag + accents, with `restore-keys` so an interrupted run resumes from the last
successful one instead of re-requesting everything. A warm run is minutes.

**Both jobs carry `timeout-minutes: 350`** — a cold fetch plus a full DDK
compile would not fit in one job under the 6-hour ceiling, which is the other
reason fetching and compiling are separate.

**The asset is size-checked before upload.** GitHub caps a release asset at
2 GB; measured coverage puts the full both-accent build near 1.4 GB, so the
`package` job fails loudly rather than at upload time if that changes. `mp3`
does not compress, so artifact and zip steps run at `compression-level: 0`.

**The manifest is deleted before staging.** It is build input, not bundle
content — shipping it would add ~7 MB of index to every install.

## The cask

Casks live in [wesleyel/homebrew-tap](https://github.com/wesleyel/homebrew-tap),
not in this repo. Each `publish` job writes its own cask with
`scripts/update-tap-cask.sh <cask> <version> <SHA256SUMS file>`; the tap CI then
audits it on push. Both workflows may publish at once, so the script rebases and
retries the push. `--variant audio` is a separate cask:
both variants install the same bundle path, so they declare each other in
`conflicts_with` and a user picks one.

Homebrew's `dictionary` stanza installs into `~/Library/Dictionaries`
(`dictionarydir`) and handles uninstall, so no custom `zap` is needed.

`scripts/update_cask.py` only seeds a new cask by hand (releases use `update-tap-cask.sh`):

```bash
python3 scripts/update_cask.py --repo owner/name --version 2.0 \
  --asset OpenDictionary.dictionary.zip \
  -o /path/to/homebrew-tap/Casks/open-dictionary.rb
brew style /path/to/homebrew-tap/Casks/open-dictionary.rb
```

```bash
brew tap wesleyel/tap
brew install --cask wesleyel/tap/open-dictionary
```

## Release shape

Tag `appledict-<source_tag>`, e.g. `appledict-v2.0`. Both workflows publish to
the same tag, adding their own assets:

| Asset | From |
|---|---|
| `OpenDictionary.dictionary.zip` + `SHA256SUMS.txt` | `build.yml` |
| `OpenDictionary-audio.dictionary.zip` + `SHA256SUMS-audio.txt` | `audio.yml` |

Whichever runs second rewrites the release notes, so both sets of notes describe
both variants. Notes include the brew commands, the manual install path, the
quarantine hint and the CC BY-SA 4.0 attribution.
