DICT_NAME  = Open Dictionary
XML        = OpenDictionary.xml
SRC        = src
DDK       ?= ./ddk
SOURCE    ?= distribution.jsonl.gz
TAG       ?= v2.0
LIMIT     ?=

export DICT_DEV_KIT_OBJ_DIR = ./objects
BUNDLE = $(DICT_DEV_KIT_OBJ_DIR)/$(DICT_NAME).dictionary

.PHONY: all ddk fetch xml dict verify zip install uninstall test clean

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

xml: $(SOURCE)
	python3 $(SRC)/build_appledict.py $(SOURCE) -o $(XML) --source-tag $(TAG) $(if $(LIMIT),--limit $(LIMIT),)
	xmllint --noout $(XML)

dict: ddk xml
	"$(DDK)/bin/build_dict.sh" -v 10.11 "$(DICT_NAME)" $(XML) \
		$(SRC)/OpenDictionary.css $(SRC)/OpenDictionary.plist
	@$(MAKE) --no-print-directory verify

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

## Fixture-driven smoke test; needs no upstream download.
test: ddk
	tests/smoke.sh --build

clean:
	rm -rf $(DICT_DEV_KIT_OBJ_DIR) $(XML) OpenDictionary.dictionary.zip
