UI_DIR := src/fleet/ui
FLEET_HOME ?= $(HOME)/.fleet
UI_DIST := $(FLEET_HOME)/ui_dist

.PHONY: ui-install ui-build ui-dev

ui-install:
	cd $(UI_DIR) && npm install

ui-build: ui-install
	cd $(UI_DIR) && npm run build
	mkdir -p $(FLEET_HOME)
	rm -rf $(UI_DIST)
	cp -r $(UI_DIR)/dist $(UI_DIST)
	@echo "UI built → $(UI_DIST)"

ui-dev:
	cd $(UI_DIR) && npm run dev
