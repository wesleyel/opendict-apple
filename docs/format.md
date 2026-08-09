# Format mapping

Source: `distribution_entry_v5`, defined in
[upstream `docs/export_contracts.md`](https://github.com/ahpxex/open-dictionary/blob/main/docs/export_contracts.md).
Target: Apple's Dictionary XML, compiled by the DDK.

## Entry shape

```xml
<d:entry id="e_en-knot-01" d:title="knot">
  <d:index d:value="knot"  d:title="knot"/>
  <d:index d:value="knots" d:title="knots → knot" d:priority="2"/>
  <h1 class="hw">knot</h1>
  <div class="audio">                        <!-- audio variant only -->
    <a class="say uk" href="Audio/3f/knot-3f52…_uk.mp3" onclick="…">🔊英</a>
    <a class="say us" href="Audio/3f/knot-3f52…_us.mp3" onclick="…">🔊美</a>
  </div>
  <div class="summary">…headword_summary…</div>
  <div class="hook"><span class="label">记忆主线</span>…memory_hook…</div>
  <div class="posgroup">
    <h2 class="pos">noun</h2>
    <div class="pron">UK /nɒt/  US /nɑt/</div>
    <div class="possum">…pos_groups[].summary…</div>
    <div class="forms">变形：knots（plural）</div>
    <ol class="senses">
      <li class="sense core">
        <span class="prio core">核心</span>
        <span class="gloss">…short_gloss…</span>
        <div class="expl">…learner_explanation…</div>
        <ul class="examples"><li><span class="en">…</span><span class="tr">…</span></li></ul>
      </li>
    </ol>
  </div>
  <div class="ety">…</div>
  <div class="notes">…study_notes…</div>
</d:entry>
```

## Field mapping

| `distribution_entry_v5` | Rendered as |
|---|---|
| `headword` | `<h1>`, `d:title`, primary `d:index` |
| `normalized_headword` | secondary `d:index` when it differs |
| `headword_summary` | `.summary` |
| `memory_hook` | `.hook`, labelled 记忆主线 |
| `study_notes[]` | `.notes` list |
| `etymology_note` / `etymologies[]` | `.ety` (note preferred, list joined as fallback) |
| `pos_groups[].pos` + `proper_name` | `<h2 class="pos">`, proper names suffixed 专名 |
| `pos_groups[].pronunciations[]` | `.pron`, tagged US/UK |
| `pos_groups[].forms[]` | `.forms`, and one `d:index` each |
| `pos_groups[].relations[]` | `.rel` |
| `meanings[].priority` | `.prio` badge + `li.sense` class |
| `meanings[].short_gloss` | `.gloss` |
| `meanings[].learner_explanation` | `.expl` — the product field |
| `meanings[].examples[]` | `.en` / `.tr` pairs |

## Indexing

`d:index` decides what a search matches. Every headword gets a
`d:priority="0"` (default) index; normalized spellings and every inflected form
get `d:priority="2"`, so searching `knots` finds the entry while `knot` still
ranks first. Inflections are titled `form → lemma` so the result list stays
readable.

## Contract rules honoured

**Priority filtering must not empty an entry.** Priorities are truthful, so a
genuinely obscure headword can consist entirely of `rare` senses. With
`--min-priority`, an entry that would render empty is re-rendered unfiltered.
The `gallimaufry` fixture covers this.

**Entries without distributable meanings are dropped** rather than emitted as
empty shells. The `emptyword` fixture covers this.

**Sub-object shapes are parsed defensively.** The contract pins the top-level
fields; `forms`, `pronunciations` and `relations` are looser. `as_text()` and
`as_tags()` probe `text` / `value` / `ipa` / `form` / `word` and the tag-ish key
names, and skip what they cannot read. The `tack` fixture feeds in bare strings
and alternate key names to keep that path honest.

## Character sanitization

XML 1.0 forbids most control characters as raw codepoints, and escaping does
not rescue them — `&#20;` is just as illegal as the byte. Upstream v2.0 carries
exactly one such character (U+0014) across all 84,212 entries, and that single
character makes the entire 310 MB document unparseable.

`_clean()` strips them inside `as_text()`, the one funnel every data-derived
string passes through, so element text and attribute values are both covered.
The count is reported on the converter's summary line:

```
read=84212 written=84212 skipped=0 stripped_control_chars=1 -> OpenDictionary.xml
```

A sudden jump in that number means upstream changed something; investigate
rather than ignore it. Fixture `en-ctrlchar-01` pins the behaviour.

Note that `xmllint` reports the cascade, not the cause. Losing sync on the
illegal character makes it accumulate the rest of the document as one text node
and report `xmlSAX2Characters: huge text node` thousands of lines later. Fix the
first error and the second disappears.

## Pronunciation audio

Two variants ship from the same source: the plain dictionary, and one with
recordings bundled. `--audio-manifest` is what separates them — without it the
converter emits no audio markup at all.

### Why the clips are bundled rather than streamed

Dictionary.app's entry view is a WebKit view with **no outbound network
access**. Measured with a probe dictionary on macOS 15:

| | result |
|---|---|
| inline `<script>` | runs |
| `setTimeout` / async callbacks | fire |
| remote `<img>` | `onerror` |
| `XMLHttpRequest` to any host | `onerror` |
| remote `<audio>` | `MEDIA_ERR_SRC_NOT_SUPPORTED` (code 4), `play()` rejects `NotSupportedError` |
| `data:` URI `<audio>` | plays |
| bundled `Audio/…mp3` (relative) | plays |

So a URL pointing at an online pronunciation endpoint renders a button that can
never make a sound. Relative paths resolve against `Contents/Resources/`, which
is where `build_dict.sh` copies `OtherResources/`.

### Two rules the markup has to respect

**The player lives on `window`.** An `Audio` referenced only by a local
variable is collectable while `play()` is still loading the file, which
produces a button that works intermittently:

```js
var w=window;if(!w._dp){w._dp=new Audio()}w._dp.src=this.href;w._dp.play();return false;
```

**Handlers must be entity-free.** Dictionary.app parses stored entry bodies as
HTML, not XHTML. Attribute values are entity-decoded, but a `<script>` body is
raw text, so an `&amp;` written to keep the XML well-formed reaches the JS
parser literally and kills the whole script. Keep `&` and `<` out of anything
executable — the smoke test asserts this.

### Coverage

Clips are keyed by the word, so one pair serves every pos_group of an entry.
About a third of upstream headwords have no recording — multi-word phrases and
hyphenated compounds mostly — and the source answers those with a deterministic
HTTP 500. `scripts/fetch_audio.py` records what it actually got in
`manifest.tsv`, and `render_audio()` emits a button only for clips listed there,
so a missing recording is a missing button rather than a dead one. Entries with
one accent only get one button.

### Layout

```
audio_files/                       # staging root, gitignored
├── OtherResources/                # copied wholesale into Contents/Resources/
│   └── Audio/<2 hex>/<slug>-<sha1[:8]>_<uk|us>.mp3
├── manifest.tsv                   # headword \t uk path \t us path
└── misses.txt                     # headwords with no recording
```

The manifest sits **outside** `OtherResources/` on purpose: the DDK copies that
directory wholesale, so anything left inside it ships to users — a 7 MB index of
the clip tree included. Paths recorded in the manifest are bundle-relative
(`Audio/…`), which is exactly what the entry markup needs.

The hash disambiguates: the slug is lowercased, so `US` and `us` would collide
on a case-insensitive volume, and it is truncated at 32 characters. Its first
byte shards the tree so no directory holds more than a few hundred of the
~110k files. Only `Audio/` is copied into the bundle; the manifest is build
input, not bundle content.

## Attribution front matter

`src/build_appledict.py` emits a first entry with id `front_back_matter`, referenced
from `src/OpenDictionary.plist` as `DCSDictionaryFrontMatterReferenceID`. It carries
the Wiktionary attribution and the CC BY-SA 4.0 notice, so a redistributed
bundle stays compliant on its own. Both `make verify` and the CI `package` job
fail if that reference is missing from the compiled `Info.plist`.

## Compiled bundle

```
Open Dictionary.dictionary/Contents/
├── Info.plist                 # from src/OpenDictionary.plist, rewritten by the DDK
└── Resources/
    ├── Body.data              # zlib-compressed entry bodies
    ├── KeyText.data           # search keys
    ├── KeyText.index          # key -> body offset
    ├── EntryID.data           # entry ids
    ├── EntryID.index          # id -> body offset, used for cross-references
    └── DefaultStyle.css       # from src/OpenDictionary.css
```

Built with `build_dict.sh -v 10.11`, which enables the trie index and stronger
body compression than the 10.5-compatible default.

## Styling

Dictionary.app renders with WebKit, so `src/OpenDictionary.css` is ordinary CSS and
`@media (prefers-color-scheme: dark)` works. Class names above are the styling
hooks; keep them in sync with `render_entry()` when editing either side.
