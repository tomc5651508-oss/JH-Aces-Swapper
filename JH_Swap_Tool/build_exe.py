import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
DIST = HERE / "dist"
WORK = HERE / "build"


def main():
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                    "--exclude-module", "PIL", "--name", "JH_Swap_Tool", "--distpath", str(DIST), "--workpath", str(WORK),
                    "--specpath", str(WORK), "--add-data", f"{HERE / 'slots.json'};.",
                    str(HERE / "jh_swap_tool.py")], check=True, cwd=HERE)
    exe = DIST / "JH_Swap_Tool.exe"
    zpath = DIST / "JH_Swap_Tool.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in (exe, HERE / "README.md", HERE / "slots.json"):
            z.write(p, p.name)
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in (exe, zpath)]
    (DIST / "JH_Swap_Tool.sha256.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
