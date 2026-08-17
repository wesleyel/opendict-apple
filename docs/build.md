# Building

## Layout

```
src/        inputs to the DDK compile: converter, CSS, plist
scripts/    auxiliary tooling (cask generator; output goes to wesleyel/homebrew-tap)
tests/      fixture + smoke test
docs/       this
ddk/        Dictionary Development Kit, cloned on demand, gitignored
objects/    build output, gitignored
```

## Pipeline

```
distribution.jsonl.gz ──src/build_appledict.py──▶ OpenDictionary.xml
                                                          │
                               src/OpenDictionary.css ────┤
                               src/OpenDictionary.plist ──┤
                                                          ▼
                                        DDK build_dict.sh ──▶ Open Dictionary.dictionary
                                                          ▼
                                                 ~/Library/Dictionaries/
```

Conversion is pure Python and streams line by line, so it runs anywhere. Only
the DDK compile step needs macOS.

## Requirements

| | |
|---|---|
| macOS | for the compile step only; the converter runs on Linux too |
| Python | 3.9+, stdlib only |
| `xmllint` | ships with macOS; `libxml2-utils` on Debian/Ubuntu |
| `gh` | only for `make fetch` |
| DDK | fetched by `make ddk`, see below |

## Dictionary Development Kit

Apple ships the DDK only inside *Additional Tools for Xcode*, behind an Apple ID
login — it is **not** part of Xcode itself, and there is no Homebrew formula.
`make ddk` clones the
[nanoskript/dictionary-development-kit](https://github.com/nanoskript/dictionary-development-kit)
mirror instead: 101 KB, and the tools under `bin/` are universal binaries
(`x86_64 arm64`), so they run natively on Apple Silicon without Rosetta.

Verify before trusting a mirror:

```bash
lipo -archs ddk/bin/build_key_index   # expect: x86_64 arm64
```

The older and more-starred `SebastianSzturo` mirror is from 2017 and carries
x86_64-only binaries — it needs Rosetta and is not used here.

If you would rather use Apple's own copy, download *Additional Tools for Xcode*
from [developer.apple.com/download/all](https://developer.apple.com/download/all/?q=Additional%20Tools),
then point the build at it:

```bash
make dict DDK="/Applications/Utilities/Dictionary Development Kit"
```

## Targets

```bash
make fetch                 # download + checksum the upstream artifact
make xml                   # JSONL -> Apple Dictionary XML
make dict                  # + compile the bundle, then verify it
make dict LIMIT=500        # trial build from the first 500 entries
make install               # + copy into ~/Library/Dictionaries
make uninstall
make zip                   # release-shaped archive + sha256
make test                  # fixture smoke test, no download needed
make clean
```

`TAG=v2.0` selects the upstream release; `SOURCE=` overrides the input path;
`DDK=` overrides the kit location.

## Audio variant

The same dictionary with pronunciation recordings inside the bundle. It is a
separate build because fetching the clips takes hours and ~1.4 GB, and a
separate release asset because that weight has no business in the default
install. Both variants compile to the same bundle identity, so a user installs
one or the other — the casks declare `conflicts_with`.

```bash
make audio                 # download every clip (hours, resumable)
make audio LIMIT=200       # trial run
make dict-audio            # convert with the manifest, compile, verify
make zip-audio             # OpenDictionary-audio.dictionary.zip + sha256
make install-audio
make clean-audio           # drop the clip cache (expensive to rebuild)
```

`ACCENTS=us` fetches American only, roughly a third of the full size.
`make audio` is resumable: it skips clips already on disk and headwords already
recorded as having no recording, so rerun it after an interrupt rather than
starting over. `AUDIO_DIR=` moves the cache off the repo.

The clip tree reaches the DDK as `OtherResources`, which `build_dict.sh`
resolves against its **working directory** with no flag to override. So the
audio build runs from `build/audio/`, where `OtherResources` is a symlink to
the cache. The plain build has no such directory, which is what keeps the two
variants from contaminating each other — `make test --build` asserts both
halves of that.

CI runs this as a separate manually-triggered workflow, `build-audio`; see
[ci.md](ci.md).

## Converter options

```bash
python3 src/build_appledict.py distribution.jsonl.gz -o OpenDictionary.xml \
  --source-tag v2.0 \        # shown on the attribution front matter page
  --min-priority common \    # drop `rare` senses (default: keep everything)
  --limit 500 \              # trial builds
  --audio-manifest audio_files/manifest.tsv \   # bundled audio variant
  --no-front-matter          # only for tests; see LICENSE-DATA.md
```

`--inspect` prints the first row's raw JSON and exits — use it whenever an
upstream release changes shape. `--version` prints the converter version, which
is also stamped into an XML comment, the front matter page and the run summary.

## Fetching audio

```bash
python3 scripts/fetch_audio.py distribution.jsonl.gz --out audio_files \
  --accents uk,us \          # or just us
  --workers 8 \              # concurrent requests
  --delay 0.05 \             # pause per request, per worker
  --limit 200 \              # trial runs
  --retry-misses             # re-request headwords previously found to have none
```

Roughly a third of headwords have no recording at all; the source signals that
with a deterministic HTTP 500, which is recorded in `misses.txt` and not
retried. Transient failures (timeouts, 429, 503) are retried with a widening
pause. See [format.md](format.md#pronunciation-audio) for the file layout and
the manifest contract.

## Troubleshooting

**Build succeeds but the dictionary is empty in Dictionary.app.** The bundle is
cached by the daemon. `make uninstall && make install`, then quit and reopen
Dictionary.app; if it persists, `killall DictionaryServiceHelper`.

**"No reference index record" note during the build.** Harmless when the front
matter is disabled; with the default front matter entry it does not appear.

**RelaxNG validation fails.** The schema at
`ddk/documents/DictionarySchema/AppleDictionarySchema.rng` `include`s XHTML
modules from `thaiopensource.com`, which is long dead, so `xmllint --relaxng`
cannot resolve it offline. Well-formedness (`xmllint --noout`) plus the DDK's
own source check is the practical gate.

**Fields render blank after an upstream release.** The distribution contract
pins the top-level fields, but the shapes of `forms`, `pronunciations` and
`relations` are less pinned down, so `src/build_appledict.py` probes a few plausible
key names and degrades silently rather than crashing. Run `--inspect` and tighten
`render_pos_group()` / `render_relations()`.

**`PCDATA invalid Char value N` from xmllint.** A control character illegal in
XML 1.0 reached the output. `as_text()` is supposed to strip these — see
[format.md](format.md#character-sanitization) — so a new one means text is
bypassing that funnel. Any `huge text node` error further down the file is a
cascade from the first one, not a separate problem.

**A downloaded zip won't install.** Clear the quarantine flag:

```bash
xattr -dr com.apple.quarantine 'Open Dictionary.dictionary'
```

**`cp: invalid option -- 'X'` during the audio build.** `build_dict.sh` copies
`OtherResources` with `cp -XRf`, and `-X` is BSD-only, so a GNU `cp` from
coreutils earlier in `PATH` aborts the build. The Makefile and the smoke test
pin `PATH=/usr/bin:/bin:/usr/sbin:/sbin` around the DDK for that reason; a
hand-run `build_dict.sh` needs the same.

**Play buttons do nothing.** Expected in the three-finger lookup popover — it
does not run JavaScript. Inside Dictionary.app they should work; if they do not,
check that clips actually reached the bundle (`make verify-audio` counts them).
A bundle built without `OtherResources` still renders buttons, because the
markup comes from the manifest, not from the files.

## Scale note

The full artifact is 84,212 entries. Conversion is a few minutes; the DDK is an
old single-threaded tool, so the compile is the long pole. Do a `LIMIT=500` run
first — it exercises the whole chain in seconds.
