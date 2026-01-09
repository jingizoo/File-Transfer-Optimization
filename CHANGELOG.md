# Changelog

## Version 1.0.0 - Project Restructure

### Improvements

1. **Easy Installation**
   - Added `setup.py` and `pyproject.toml` for pip installation
   - Created `install.sh` script for one-command installation
   - Added `Makefile` for convenient build targets
   - Package installs as `fast-xfer` command-line tool

2. **Better Documentation**
   - Comprehensive `README.md` with examples and troubleshooting
   - Quick start guide (`QUICKSTART.md`)
   - Example usage script (`examples.sh`)
   - Clear installation instructions for Unix systems

3. **Code Enhancements**
   - Added progress messages for better user feedback
   - Improved error messages
   - Better logging of compression and transfer steps
   - Cleanup messages for temporary files

4. **Project Structure**
   - Proper `.gitignore` for Python projects
   - `requirements.txt` (notes system dependencies)
   - Standard Python package structure

5. **User Experience**
   - Installable as system command (`fast-xfer`)
   - Multiple installation methods (pip, script, Makefile)
   - Clear error messages for common issues
   - Better progress indicators

### Installation Methods

1. **pip install** (recommended)
   ```bash
   pip3 install --user .
   ```

2. **Install script**
   ```bash
   bash install.sh
   ```

3. **Makefile**
   ```bash
   make install-user
   ```

4. **Direct usage**
   ```bash
   ./fast_xfer.py <source> <target>
   ```

### Usage

After installation:
```bash
fast-xfer /path/to/file.txt user@host:/data/replica/
```

Direct script usage:
```bash
python3 fast_xfer.py /path/to/file.txt user@host:/data/replica/
```

