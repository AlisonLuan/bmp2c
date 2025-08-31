#!/usr/bin/env bash
set -euo pipefail

# Run:
#   bash ./build.sh
# After it finishes, check ./output/ for bmp2c-gui.exe and/or bmp2c.exe

repo="$(cd "$(dirname "$0")" && pwd)"
cd "$repo"

# Clean old artifacts
rm -rf output build dist .venv_build launcher_gui.py launcher_cli.py

# Fresh venv (throwaway just for building)
python -m venv .venv_build
# shellcheck disable=SC1091
source .venv_build/Scripts/activate

python -m pip install -U pip setuptools wheel
# Install your project + PyInstaller
pip install -e .
pip install pyinstaller

# Create small entry stubs
cat > launcher_gui.py << 'PY'
from bmp2c.gui import main
if __name__ == "__main__":
    main()
PY

cat > launcher_cli.py << 'PY'
from bmp2c.cli import main
if __name__ == "__main__":
    main()
PY

# Build GUI (no console)
pyinstaller --onefile --windowed --name bmp2c-gui launcher_gui.py

# Build CLI (with console)
pyinstaller --onefile --console --name bmp2c launcher_cli.py

# Collect outputs
mkdir -p output
mv dist/*.exe output/

echo
echo "✅ Done. EXEs in: $repo/output"
echo "   - $repo/output/bmp2c-gui.exe"
echo "   - $repo/output/bmp2c.exe"
