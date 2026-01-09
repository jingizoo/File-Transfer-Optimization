#!/usr/bin/env python3
"""Setup script for fast_xfer."""

from setuptools import setup
from pathlib import Path

# Read the README file
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""

setup(
    name="fast-xfer",
    version="1.0.0",
    description="Highly-tuned Linux-to-Linux file transfer wrapper (rsync/ssh, optional zstd, optional chunk parallelism)",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="File Transfer Optimization",
    url="https://github.com/yourusername/fast-xfer",
    py_modules=["fast_xfer"],
    entry_points={
        "console_scripts": [
            "fast-xfer=fast_xfer:main",
        ],
    },
    python_requires=">=3.7",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Archiving",
        "Topic :: System :: Systems Administration",
    ],
)

