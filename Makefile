.PHONY: install install-user uninstall test clean help

help:
	@echo "fast-xfer Makefile"
	@echo ""
	@echo "Targets:"
	@echo "  install       - Install system-wide (requires sudo)"
	@echo "  install-user  - Install for current user only (recommended)"
	@echo "  uninstall     - Uninstall the package"
	@echo "  test          - Run basic tests"
	@echo "  clean         - Remove build artifacts"
	@echo ""

install:
	pip3 install .

install-user:
	pip3 install --user .

uninstall:
	pip3 uninstall -y fast-xfer || true

test:
	@echo "Testing fast-xfer installation..."
	@python3 -c "import fast_xfer; print('✓ Module imports successfully')" || echo "✗ Module import failed"
	@command -v fast-xfer >/dev/null 2>&1 && echo "✓ fast-xfer command found" || echo "✗ fast-xfer command not in PATH"

clean:
	rm -rf build/ dist/ *.egg-info __pycache__/ .pytest_cache/

