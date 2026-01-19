# Fixing Oracle DB "cmake version error"

The `oracledb` Python package sometimes tries to build from source, which requires cmake. Here are solutions:

## Solution 1: Install Pre-built Wheel (RECOMMENDED)

Use a pre-built wheel instead of building from source:

```bash
# Uninstall any existing oracledb
pip3 uninstall oracledb -y

# Install with pre-built wheels (no cmake needed)
pip3 install --only-binary :all: oracledb

# OR if that doesn't work, try:
pip3 install --upgrade pip setuptools wheel
pip3 install oracledb
```

## Solution 2: Update cmake (if building from source)

If you must build from source:

```bash
# Check cmake version
cmake --version

# Update cmake (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y cmake

# OR download latest from cmake.org
```

## Solution 3: Install Oracle Instant Client (REQUIRED)

`oracledb` requires Oracle Instant Client. Install it first:

### Linux (Ubuntu/Debian):
```bash
# Download Oracle Instant Client Basic Package
# From: https://www.oracle.com/database/technologies/instant-client/linux-x86-64-downloads.html

# Example installation:
cd /tmp
wget https://download.oracle.com/otn_software/linux/instantclient/instantclient-basic-linux.x64-21.1.0.0.0.zip
unzip instantclient-basic-linux.x64-21.1.0.0.0.zip
sudo mkdir -p /opt/oracle
sudo mv instantclient_21_1 /opt/oracle/
sudo sh -c "echo /opt/oracle/instantclient_21_1 > /etc/ld.so.conf.d/oracle-instantclient.conf"
sudo ldconfig
export LD_LIBRARY_PATH=/opt/oracle/instantclient_21_1:$LD_LIBRARY_PATH
```

### Or use system package (if available):
```bash
# Some distributions have packages
sudo apt-get install -y libaio1
# Then download and install Instant Client manually
```

## Solution 4: Use Thin Mode (No Instant Client Needed)

`oracledb` 2.0+ supports "thin mode" which doesn't require Oracle Instant Client:

```python
import oracledb

# Use thin mode (no Instant Client needed)
oracledb.init_oracle_client()  # Optional, enables thin mode by default in newer versions

# Your connection code works the same
conn = oracledb.connect(user=..., password=..., dsn=...)
```

**Note:** Thin mode may have some limitations compared to thick mode.

## Solution 5: Check Python and Platform Compatibility

```bash
# Check Python version
python3 --version  # Should be 3.7+

# Check if you're on a supported platform
python3 -c "import platform; print(platform.platform())"

# Try installing with verbose output to see the error
pip3 install -v oracledb
```

## Quick Test After Installation

```bash
python3 -c "import oracledb; print('oracledb version:', oracledb.__version__)"
```

If this works, the package is installed correctly.

## If All Else Fails: Use cx_Oracle (Legacy)

As a last resort, you can use the older `cx_Oracle` package (now deprecated but still works):

```bash
pip3 install cx_Oracle
```

Then change your import:
```python
import cx_Oracle as oracledb  # Works as drop-in replacement
```

---

## Recommended Installation Order

1. **Install Oracle Instant Client** (if not using thin mode)
2. **Update pip, setuptools, wheel**: `pip3 install --upgrade pip setuptools wheel`
3. **Install oracledb with pre-built wheels**: `pip3 install --only-binary :all: oracledb`
4. **Test**: `python3 -c "import oracledb; print(oracledb.__version__)"`
