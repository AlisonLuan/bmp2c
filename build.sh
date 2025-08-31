#!/usr/bin/env bash
set -euo pipefail

# After it finishes, check ./output/ for bmp2c-gui.exe / bmp2c.exe

repo="$(cd "$(dirname "$0")" && pwd)"
cd "$repo"

png_icon="src/bmp2c/logo.png"
build_dir=".venv_build"
work_dir=".build_assets"
ico_icon="$work_dir/icon.ico"

# Clean
rm -rf output build dist "$build_dir" "$work_dir" launcher_gui.py launcher_cli.py

# Fresh venv
python -m venv "$build_dir"
# shellcheck disable=SC1091
source "$build_dir/Scripts/activate"

python -m pip install -U pip setuptools wheel
pip install -e .
pip install pyinstaller pillow

mkdir -p "$work_dir"

# Convert PNG -> ICO
python - <<PY
from PIL import Image
from pathlib import Path
png = Path(r"$png_icon")
ico = Path(r"$ico_icon")
ico.parent.mkdir(parents=True, exist_ok=True)
img = Image.open(png).convert("RGBA")
sizes = [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
img.save(ico, sizes=sizes)
print("ICO written:", ico)
PY

# Entry stubs
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

# Build GUI (no console) with icon
pyinstaller --onefile --windowed --name bmp2c-gui --icon "$ico_icon" \
  --add-data "$png_icon;bmp2c" \
  launcher_gui.py

# Build CLI (console) with icon
pyinstaller --onefile --console  --name bmp2c     --icon "$ico_icon" \
  --add-data "$png_icon;bmp2c" \
  launcher_cli.py

# Collect outputs
mkdir -p output
mv dist/*.exe output/

echo
echo "✅ Done. EXEs in: $repo/output"
echo "   - $repo/output/bmp2c-gui.exe"
echo "   - $repo/output/bmp2c.exe"
