ADDON_ID = $(shell xmllint -xpath "string(/addon/@id)" addon.xml)
VERSION = $(shell xmllint -xpath "string(/addon/@version)" addon.xml)

PYTHON_FILES = addon_entry.py $(shell find resources/ -name "*.py")
PLAYLIST_FILE = resources/bouyguestv.m3u8
ASSET_FILES = resources/icon.png resources/fanart.jpg
LANGUAGE_FILES = $(wildcard resources/language/*/strings.po)
DOC_FILES = README.md LICENSE
ADDON_FILES = addon.xml resources/settings.xml $(PYTHON_FILES) $(ASSET_FILES) $(PLAYLIST_FILE) $(LANGUAGE_FILES) $(DOC_FILES)
ADDON_PACKAGE_FILE = $(ADDON_ID)-$(VERSION).zip

ICON_SIZE = 512

KODI_ADDON_DIR = $(HOME)/.kodi/addons
KODI_BRANCH = leia


all: package


%.png: %.svg
	rsvg-convert $< -w $(ICON_SIZE) -f png -o $@


$(PLAYLIST_FILE):
	echo "#EXTM3U" >$@
	curl "https://www.bouyguestelecom.fr/tv-direct/data/list-chaines.json" \
	    | jq -r '.body[] | ("#EXTINF: -1 tvg-name=\"" + .title + "\" tvg-logo=\"" + .logoUrl + "\" tvg-chno=\"" + (.zapNumber | tostring) + "\" group-title=\"" + .genre + "\"," + .title + "\nplugin://plugin.video.bouyguestv/?mode=watch&channel=" + (.title | @uri))' >>$@


playlist: $(PLAYLIST_FILE)


$(ADDON_PACKAGE_FILE): $(ADDON_FILES)
	ln -s . $(ADDON_ID)
	zip -FSr $@ $(foreach f,$^,$(ADDON_ID)/$(f))
	$(RM) $(ADDON_ID)


package: $(ADDON_PACKAGE_FILE)


install: $(ADDON_PACKAGE_FILE)
	unzip -o $< -d $(KODI_ADDON_DIR)


uninstall:
	$(RM) -r $(KODI_ADDON_DIR)/$(ADDON_ID)/


lint:
	flake8 $(PYTHON_FILES)
	pylint $(PYTHON_FILES)
	mypy $(PYTHON_FILES)
	bandit $(PYTHON_FILES)


check: $(ADDON_PACKAGE_FILE)
	$(eval TEMP_DIR := $(shell mktemp -d -p /var/tmp))
	unzip -o $< -d $(TEMP_DIR)
	kodi-addon-checker --branch $(KODI_BRANCH) $(TEMP_DIR)
	$(RM) -r $(TEMP_DIR)


tag: lint check
	git tag $(VERSION)
	git push origin $(VERSION)


clean:
	$(RM) $(ADDON_PACKAGE_FILE)
	$(RM) $(shell find . -name "*~")


mrproper: clean
	$(RM) resources/icon.png $(PLAYLIST_FILE)


.PHONY: playlist package install uninstall lint check tag clean mrproper
