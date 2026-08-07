# Building

## Layout

```
src/        inputs to the DDK compile: converter, CSS, plist
scripts/    auxiliary tooling (cask generator)
tests/      fixture + smoke test
docs/       this
Casks/      generated Homebrew cask
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

## Converter options

```bash
python3 src/build_appledict.py distribution.jsonl.gz -o OpenDictionary.xml \
  --source-tag v2.0 \        # shown on the attribution front matter page
  --min-priority common \    # drop `rare` senses (default: keep everything)
  --limit 500 \              # trial builds
  --no-front-matter          # only for tests; see LICENSE-DATA.md
```

`--inspect` prints the first row's raw JSON and exits — use it whenever an
upstream release changes shape.

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

## Scale note

The full artifact is 84,212 entries. Conversion is a few minutes; the DDK is an
old single-threaded tool, so the compile is the long pole. Do a `LIMIT=500` run
first — it exercises the whole chain in seconds.
