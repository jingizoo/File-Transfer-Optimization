#!/bin/bash
# Installation script for fast-xfer

set -e

echo "=== fast-xfer Installation Script ==="
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Please install Python 3.7 or later."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Found Python $PYTHON_VERSION"

# Check for required system tools
echo ""
echo "Checking system dependencies..."

MISSING_DEPS=()

if ! command -v ssh &> /dev/null; then
    MISSING_DEPS+=("ssh")
fi

if ! command -v rsync &> /dev/null; then
    MISSING_DEPS+=("rsync")
fi

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo "WARNING: Missing required dependencies: ${MISSING_DEPS[*]}"
    echo "Please install them using your package manager:"
    echo "  Debian/Ubuntu: sudo apt-get install openssh-client rsync"
    echo "  RHEL/CentOS:   sudo yum install openssh-clients rsync"
    echo "  macOS:         brew install openssh rsync"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for optional dependencies
if ! command -v zstd &> /dev/null; then
    echo "INFO: zstd not found (optional, for compression strategies)"
    echo "      Install with: sudo apt-get install zstd (or equivalent)"
fi

# Install Python package
echo ""
echo "Installing fast-xfer..."
echo ""

if [ -f "pyproject.toml" ]; then
    # Modern pip installation
    pip3 install --user .
else
    # Fallback to setup.py
    pip3 install --user .
fi

# Check if installation was successful
if command -v fast-xfer &> /dev/null; then
    echo ""
    echo "✓ Installation successful!"
    echo ""
    echo "Usage:"
    echo "  fast-xfer <source> <target>"
    echo ""
    echo "Example:"
    echo "  fast-xfer /data/file.txt user@10.0.0.15:/data/replica/"
    echo ""
    echo "For more information, see README.md or run:"
    echo "  fast-xfer --help"
else
    echo ""
    echo "WARNING: Installation completed but 'fast-xfer' command not found in PATH."
    echo "You may need to add ~/.local/bin to your PATH:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
    echo "Or use the script directly:"
    echo "  python3 fast_xfer.py <source> <target>"
fi

