DICT_NAME  = Open Dictionary
XML        = OpenDictionary.xml
XML_AUDIO  = OpenDictionaryAudio.xml
SRC        = src
DDK       ?= ./ddk
SOURCE    ?= distribution.jsonl.gz
TAG       ?= v2.0
LIMIT     ?=

# Bundled pronunciation clips: staged here by `make audio`, gitignored, and
# handed to the DDK as OtherResources (see the audio-stage target).
AUDIO_DIR ?= audio_files
MANIFEST   = $(AUDIO_DIR)/manifest.tsv
ACCENTS   ?= uk,us

export DICT_DEV_KIT_OBJ_DIR = ./objects
BUNDLE = $(DICT_DEV_KIT_OBJ_DIR)/$(DICT_NAME).dictionary

OBJ_AUDIO    = ./objects-audio
BUNDLE_AUDIO = $(OBJ_AUDIO)/$(DICT_NAME).dictionary
STAGE_AUDIO  = ./build/audio

# Stamps, not the bundle's own Info.plist: DICT_NAME contains a space, and make
# would read "objects/Open Dictionary.dictionary/…" as two separate targets —
# which silently let the two variants' rules override each other.
STAMP       = $(DICT_DEV_KIT_OBJ_DIR)/.built
STAMP_AUDIO = $(OBJ_AUDIO)/.built

# build_dict.sh copies OtherResources with `cp -XRf`; -X is BSD-only, so a
# coreutils `cp` earlier in PATH kills the audio build. Pin the system tools.
DDK_ENV = env PATH=/usr/bin:/bin:/usr/sbin:/sbin

# xml/dict are real file targets so `make install` after a build does not redo
# the 3-minute compile; the phony names stay as convenient aliases.
.PHONY: all ddk fetch xml dict verify zip install uninstall test clean \
        audio audio-stage xml-audio dict-audio verify-audio zip-audio \
        install-audio clean-audio

all: dict

## Vendor Apple's Dictionary Development Kit (universal-binary mirror).
ddk:
	@test -d $(DDK) || git clone --depth 1 https://github.com/nanoskript/dictionary-development-kit $(DDK)
	@chmod +x $(DDK)/bin/*

## Download the upstream data artifact (~97 MB) and verify its checksum.
fetch:
	gh release download $(TAG) --repo ahpxex/open-dictionary \
		--pattern 'distribution.jsonl.gz' --pattern 'SHA256SUMS.txt' --clobber
	grep distribution.jsonl.gz SHA256SUMS.txt | shasum -a 256 -c -

$(XML): $(SOURCE) $(SRC)/build_appledict.py
	python3 $(SRC)/build_appledict.py $(SOURCE) -o $(XML) --source-tag $(TAG) $(if $(LIMIT),--limit $(LIMIT),)
	xmllint --noout $(XML)

xml: $(XML)

$(STAMP): $(XML) $(SRC)/OpenDictionary.css $(SRC)/OpenDictionary.plist | ddk
	$(DDK_ENV) "$(DDK)/bin/build_dict.sh" -v 10.11 "$(DICT_NAME)" $(XML) \
		$(SRC)/OpenDictionary.css $(SRC)/OpenDictionary.plist
	@$(MAKE) --no-print-directory verify
	@touch $(STAMP)

dict: $(STAMP)

verify:
	@for f in Info.plist Resources/Body.data Resources/KeyText.data \
	          Resources/KeyText.index Resources/EntryID.index Resources/DefaultStyle.css; do \
		test -s "$(BUNDLE)/Contents/$$f" || { echo "missing Contents/$$f"; exit 1; }; \
	done
	@plutil -lint "$(BUNDLE)/Contents/Info.plist" >/dev/null
	@grep -q front_back_matter "$(BUNDLE)/Contents/Info.plist" || { echo "attribution front matter lost"; exit 1; }
	@du -sh "$(BUNDLE)"

zip: verify
	ditto -c -k --sequesterRsrc --keepParent "$(BUNDLE)" OpenDictionary.dictionary.zip
	shasum -a 256 OpenDictionary.dictionary.zip

install: dict
	mkdir -p ~/Library/Dictionaries
	ditto --noextattr --norsrc "$(BUNDLE)" "$(HOME)/Library/Dictionaries/$(DICT_NAME).dictionary"
	touch ~/Library/Dictionaries
	@echo "Installed. Enable it in Dictionary.app > Settings."

uninstall:
	rm -rf "$(HOME)/Library/Dictionaries/$(DICT_NAME).dictionary"

# --- audio variant ---------------------------------------------------------
# Same dictionary, same bundle identity, plus ~110k bundled clips. The two
# variants are alternatives, not companions: installing one replaces the other.

## Download every clip (hours, ~1.4 GB). Resumable — rerun after an interrupt.
audio: $(SOURCE)
	python3 scripts/fetch_audio.py $(SOURCE) --out $(AUDIO_DIR) --accents $(ACCENTS) \
		$(if $(LIMIT),--limit $(LIMIT),)

$(XML_AUDIO): $(SOURCE) $(SRC)/build_appledict.py $(MANIFEST)
	python3 $(SRC)/build_appledict.py $(SOURCE) -o $(XML_AUDIO) --source-tag $(TAG) \
		--audio-manifest $(MANIFEST) $(if $(LIMIT),--limit $(LIMIT),)
	xmllint --noout $(XML_AUDIO)

xml-audio: $(XML_AUDIO)

# build_dict.sh looks for ./OtherResources relative to its working directory
# and has no flag for it, so the audio build runs from a staging dir whose
# OtherResources points at the clip tree. The plain build has no such dir,
# which is what keeps the two variants from contaminating each other.
audio-stage:
	@test -s $(MANIFEST) || { echo "no $(MANIFEST) — run 'make audio' first"; exit 1; }
	@mkdir -p $(STAGE_AUDIO)
	@rm -f $(STAGE_AUDIO)/OtherResources
	@ln -s "$(abspath $(AUDIO_DIR))/OtherResources" $(STAGE_AUDIO)/OtherResources

$(STAMP_AUDIO): $(XML_AUDIO) $(SRC)/OpenDictionary.css $(SRC)/OpenDictionary.plist | ddk
	@$(MAKE) --no-print-directory audio-stage
	cd $(STAGE_AUDIO) && $(DDK_ENV) DICT_DEV_KIT_OBJ_DIR="$(abspath $(OBJ_AUDIO))" \
		"$(abspath $(DDK))/bin/build_dict.sh" -v 10.11 "$(DICT_NAME)" \
		"$(abspath $(XML_AUDIO))" "$(abspath $(SRC))/OpenDictionary.css" \
		"$(abspath $(SRC))/OpenDictionary.plist"
	@$(MAKE) --no-print-directory verify-audio
	@touch $(STAMP_AUDIO)

dict-audio: $(STAMP_AUDIO)

verify-audio:
	@for f in Info.plist Resources/Body.data Resources/KeyText.data \
	          Resources/KeyText.index Resources/EntryID.index Resources/DefaultStyle.css; do \
		test -s "$(BUNDLE_AUDIO)/Contents/$$f" || { echo "missing Contents/$$f"; exit 1; }; \
	done
	@plutil -lint "$(BUNDLE_AUDIO)/Contents/Info.plist" >/dev/null
	@grep -q front_back_matter "$(BUNDLE_AUDIO)/Contents/Info.plist" || { echo "attribution front matter lost"; exit 1; }
	@n=$$(find "$(BUNDLE_AUDIO)/Contents/Resources/Audio" -name '*.mp3' 2>/dev/null | wc -l); \
		test "$$n" -gt 0 || { echo "no clips in the bundle — OtherResources was not copied"; exit 1; }; \
		echo "bundled clips: $$n"
	@du -sh "$(BUNDLE_AUDIO)"

zip-audio: verify-audio
	ditto -c -k --sequesterRsrc --keepParent "$(BUNDLE_AUDIO)" OpenDictionary-audio.dictionary.zip
	shasum -a 256 OpenDictionary-audio.dictionary.zip

install-audio: dict-audio
	mkdir -p ~/Library/Dictionaries
	ditto --noextattr --norsrc "$(BUNDLE_AUDIO)" "$(HOME)/Library/Dictionaries/$(DICT_NAME).dictionary"
	touch ~/Library/Dictionaries
	@echo "Installed (with audio). Enable it in Dictionary.app > Settings."

## Fixture-driven smoke test; needs no upstream download.
test: ddk
	tests/smoke.sh --build

clean:
	rm -rf $(DICT_DEV_KIT_OBJ_DIR) $(OBJ_AUDIO) $(STAGE_AUDIO) $(XML) $(XML_AUDIO) \
		OpenDictionary.dictionary.zip OpenDictionary-audio.dictionary.zip

## Clip cache is expensive to rebuild — dropped only on request.
clean-audio:
	rm -rf $(AUDIO_DIR)
