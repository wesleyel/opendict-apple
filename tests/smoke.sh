#!/bin/bash
# Fixture-driven smoke test. Runs without the 97 MB upstream artifact.
#   tests/smoke.sh            # convert + validate XML
#   tests/smoke.sh --build    # also compile a real .dictionary (macOS + DDK)
set -euo pipefail

cd "$(dirname "$0")/.."
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
XML="$WORK/Open Dictionary.xml"

echo "==> convert fixture"
python3 src/build_appledict.py tests/fixture.jsonl -o "$XML" --source-tag smoke

echo "==> xml is well-formed"
xmllint --noout "$XML"

echo "==> content assertions"
python3 - "$XML" <<'PY'
import sys
x = open(sys.argv[1], encoding="utf-8").read()

def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        sys.exit(1)

check("attribution front matter present", "front_back_matter" in x and "CC BY-SA 4.0" in x)
check("headword indexed", '<d:index d:value="knot"' in x)
check("inflection indexed at lower priority", 'd:value="knots"' in x and 'd:priority="2"' in x)
check("US/UK pronunciations split", "UK /nɒt/" in x and "US /nɑt/" in x)
check("bilingual example rendered", "在绳子上打个结" in x)
check("all-rare entry falls back to full render", "gallimaufry" in x)
check("entry without meanings dropped", "emptyword" not in x)
# The contract pins top-level fields only; sub-object shapes must degrade, not crash.
check("loose forms shape parsed", "tacks" in x)
check("loose pronunciation shape parsed", "/tæk/" in x)
check("loose relation shape parsed", "pin" in x)
# One stray control character makes the whole 310 MB document unparseable,
# and escaping does not help — they are illegal as raw codepoints. Fixture
# en-ctrlchar-01 mirrors the single U+0014 that upstream v2.0 carries.
import re
invalid = re.compile(
    "[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)
check("no characters illegal in XML 1.0", not invalid.search(x))
check("control-char entry still rendered", "厨师" in x)
PY

echo "==> priority filter"
python3 src/build_appledict.py tests/fixture.jsonl -o "$WORK/core.xml" --min-priority core --no-front-matter
grep -q "树瘤" "$WORK/core.xml" && { echo "  FAIL rare sense leaked through --min-priority core"; exit 1; }
grep -q "gallimaufry" "$WORK/core.xml" || { echo "  FAIL all-rare entry must survive filtering"; exit 1; }
echo "  ok   rare senses filtered, all-rare entry retained"

if [[ "${1:-}" == "--build" ]]; then
  echo "==> compile .dictionary"
  [[ -d ddk ]] || git clone --depth 1 -q https://github.com/nanoskript/dictionary-development-kit ddk
  chmod +x ddk/bin/*
  DICT_DEV_KIT_OBJ_DIR="$WORK/objects" ./ddk/bin/build_dict.sh -v 10.11 \
    "Open Dictionary" "$XML" src/OpenDictionary.css src/OpenDictionary.plist
  BUNDLE="$WORK/objects/Open Dictionary.dictionary/Contents"
  for f in Info.plist Resources/Body.data Resources/KeyText.data Resources/KeyText.index \
           Resources/EntryID.index Resources/DefaultStyle.css; do
    test -s "$BUNDLE/$f" || { echo "  FAIL missing Contents/$f"; exit 1; }
  done
  grep -q front_back_matter "$BUNDLE/Info.plist" \
    || { echo "  FAIL front matter reference lost"; exit 1; }
  echo "  ok   bundle complete"
fi

echo "==> smoke passed"
