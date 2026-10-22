"""Build the standalone patcher with PyInstaller, for the system that runs it.

    python tools/build_exe.py          # the window: patch-gui.py
    python tools/build_exe.py --cli    # the command line: patch.py

PyInstaller cannot cross-build, so each system makes its own:

    Windows   1ScreenHGSS-<version>.exe              one file, windowed
    macOS     1ScreenHGSS-<version>.app, and a .zip of it for sharing
    Linux     1ScreenHGSS-<version>-linux-<arch>      one file

and `--cli` makes `1screenhgss-cli-<version>-<os>-<arch>` (`.exe` on Windows), a
one-file build of patch.py that takes the same arguments. The release workflow
(.github/workflows/release.yml) runs this on all three.

Things this has to get right, all easy to get wrong by accident:

* PyInstaller writes to `build/` and `dist/` by default. `build/` in this repo
  already holds unpacked ROM modules and is gitignored, so a default run would
  scatter its work in among them. Both paths are redirected to `dist-gui/`.
* The patcher reads `onescreen/payload/hook.bin` and `hook.json` at runtime, so
  they are bundled as data. `onescreen/rom.py` resolves them relative to its own
  file, which PyInstaller reproduces under `sys._MEIPASS`, so no code change is
  needed for the frozen build to find them.
* macOS wants an .app bundle rather than one file - PyInstaller is retiring
  one-file .app builds - and an .icns icon, made here from the committed PNG
  with the system's own sips and iconutil. The Tk it bundles is the build
  Python's: Apple's /usr/bin/python3 carries the deprecated Tk 8.5, so build
  with a Python that has Tk 8.6. Tk 9 builds run, but tkinterdnd2's library is
  compiled for Tcl 8, so they lose drag and drop.
"""

import argparse
import pathlib
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "dist-gui"
BUNDLE_ID = "io.github.yabi4.onescreenhgss"

sys.path.insert(0, str(ROOT))
from onescreen import __version__  # noqa: E402


def system():
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def arch():
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)


def make_icns(png: pathlib.Path, work: pathlib.Path) -> pathlib.Path:
    """An .icns from the 256 px PNG, through an iconset of the sizes it covers."""
    iconset = work / "1screenhgss.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir(parents=True)
    for name, px in (("16x16", 16), ("16x16@2x", 32), ("32x32", 32), ("32x32@2x", 64),
                     ("128x128", 128), ("128x128@2x", 256), ("256x256", 256)):
        subprocess.run(["sips", "-z", str(px), str(px), str(png),
                        "--out", str(iconset / f"icon_{name}.png")],
                       check=True, capture_output=True)
    icns = work / "1screenhgss.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
    return icns


def finish_app(app: pathlib.Path):
    """Give the bundle its version and the macOS display settings, then sign it
    again: PyInstaller signs ad hoc, and editing Info.plist breaks that seal."""
    plist_path = app / "Contents" / "Info.plist"
    with plist_path.open("rb") as fh:
        info = plistlib.load(fh)
    info.update({
        "CFBundleName": "1ScreenHGSS",
        "CFBundleDisplayName": "1ScreenHGSS",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "10.13",
    })
    with plist_path.open("wb") as fh:
        plistlib.dump(info, fh)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)],
                   check=True, capture_output=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cli", action="store_true",
                    help="build patch.py as a command-line program instead of the window")
    args = ap.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is required.  pip install pyinstaller")

    payload = ROOT / "onescreen" / "payload"
    if not (payload / "hook.bin").is_file():
        sys.exit(f"missing {payload/'hook.bin'} - run tools/make_payload.py first")
    assets = ROOT / "assets"
    ico, png = assets / "1screenhgss.ico", assets / "1screenhgss.png"
    if not ico.is_file() or not png.is_file():
        sys.exit(f"missing {ico} or {png} - run tools/make_icon.py first")

    os_name, work = system(), OUT / "work"
    if args.cli:
        name = f"1screenhgss-cli-{__version__}-{os_name}-{arch()}"
        script, mode = ROOT / "patch.py", ["--onefile", "--console"]
    elif os_name == "macos":
        name = f"1ScreenHGSS-{__version__}"
        script, mode = ROOT / "patch-gui.py", ["--onedir", "--windowed",
                                               "--osx-bundle-identifier", BUNDLE_ID]
    elif os_name == "windows":
        name = f"1ScreenHGSS-{__version__}"
        script, mode = ROOT / "patch-gui.py", ["--onefile", "--windowed"]
    else:
        name = f"1ScreenHGSS-{__version__}-linux-{arch()}"
        script, mode = ROOT / "patch-gui.py", ["--onefile"]

    if os_name == "macos":
        work.mkdir(parents=True, exist_ok=True)
        icon = make_icns(png, work)
    elif os_name == "windows":
        icon = ico
    else:
        icon = None                     # Linux executables carry no icon

    # ';' is the separator PyInstaller wants on Windows, ':' elsewhere.
    sep = ";" if os_name == "windows" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", *mode,
        "--name", name,
        "--add-data", f"{payload}{sep}onescreen/payload",
        "--add-data", f"{assets}{sep}assets",
        *(["--icon", str(icon)] if icon else []),
        "--workpath", str(work),
        "--distpath", str(OUT),
        "--specpath", str(OUT),
        str(script),
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    built = []
    if os_name == "macos" and not args.cli:
        app = OUT / f"{name}.app"
        if not app.is_dir():
            sys.exit("PyInstaller reported success but produced no .app")
        finish_app(app)
        shutil.rmtree(OUT / name, ignore_errors=True)     # the bare onedir copy
        archive = OUT / f"{name}-macos-{arch()}.zip"
        archive.unlink(missing_ok=True)
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(archive)],
                       check=True)
        built = [app, archive]
    else:
        exe = OUT / (name + (".exe" if os_name == "windows" else ""))
        if not exe.is_file():
            sys.exit(f"PyInstaller reported success but produced no {exe.name}")
        built = [exe]
        if os_name != "windows":
            # Downloads lose the executable bit - GitHub's artifact zips drop it -
            # so a .tar.gz carries it for anyone who fetches the build.
            archive = OUT / f"{name}.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                info = tar.gettarinfo(str(exe), arcname=exe.name)
                info.mode = 0o755
                with exe.open("rb") as fh:
                    tar.addfile(info, fh)
            built.append(archive)
    shutil.rmtree(work, ignore_errors=True)
    for path in built:
        size = (sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                if path.is_dir() else path.stat().st_size)
        print(f"  built {path}  ({size:,} bytes)")


if __name__ == "__main__":
    main()
