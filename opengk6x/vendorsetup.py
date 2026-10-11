"""Copy what OpenGK6X needs out of the official app's installer into ~/.local/share/opengk6x/vendor.

The installer ("GK6X Setup 8.0.7.exe", or the .zip it's downloaded in) is an NSIS archive holding app-64.7z,
which holds the Electron app; its resources/app.asar has the per-model data (resources/device/) and the effect and
macro libraries (resources/res/data/{le,macro}). Unpacking the NSIS and 7z layers needs `7z` (p7zip).
"""
import json
import shutil
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

DATA_DIR = Path.home() / ".local/share/opengk6x/vendor"
WANTED = ("resources/device/", "resources/res/data/le/", "resources/res/data/macro/")


def asar_entries(path: Path):
    """(name, offset, size) of every file in an Electron .asar archive."""
    with open(path, "rb") as f:
        _, header_size, _, json_len = struct.unpack("<4I", f.read(16))
        tree = json.loads(f.read(json_len))
    base = 8 + header_size

    def walk(node, prefix):
        for name, entry in node["files"].items():
            if "files" in entry:
                yield from walk(entry, f"{prefix}{name}/")
            elif "offset" in entry and not entry.get("unpacked"):
                yield f"{prefix}{name}", base + int(entry["offset"]), entry["size"]
    yield from walk(tree, "")


def _7z(*args):
    exe = shutil.which("7z") or shutil.which("7za")
    if exe is None:
        raise RuntimeError("7z isn't installed (Arch: sudo pacman -S 7zip)")
    subprocess.run([exe, *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _find_asar(src: Path, work: Path) -> Path:
    if src.is_dir():
        for cand in (src / "resources/app.asar", src / "app.asar"):
            if cand.is_file():
                return cand
        raise ValueError(f"no resources/app.asar in {src}")
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            exes = [n for n in z.namelist() if n.lower().endswith(".exe")]
            if not exes:
                raise ValueError(f"{src} has no installer (.exe) in it")
            z.extract(exes[0], work)
            src = work / exes[0]
    if src.suffix.lower() == ".asar":
        return src
    _7z("x", "-y", f"-o{work / 'nsis'}", str(src), "$PLUGINSDIR/app-64.7z")
    inner = work / "nsis" / "$PLUGINSDIR" / "app-64.7z"
    if not inner.is_file():
        raise ValueError(f"{src.name} doesn't look like the GK6X installer (no app-64.7z inside)")
    _7z("x", "-y", f"-o{work / 'app'}", str(inner), "resources/app.asar")
    return work / "app" / "resources" / "app.asar"


def _default_library(f, entries) -> list[dict]:
    """The effect list the official UI starts every keyboard with (GUID, name, LeCate = the layout an effect
    was drawn for, LeType "combination" = online-only). It's only in the UI bundle, as a JS literal."""
    import re
    for name, offset, size in entries:
        if not (name.startswith("ui/js/") and name.endswith(".js")):
            continue
        f.seek(offset)
        text = f.read(size).decode("utf-8", errors="replace")
        start = text.find("les:[{GUID:")
        if start < 0:
            continue
        end = text.find("}]", start)
        out = []
        for m in re.finditer(r'\{GUID:"([^"]+)",Name:"([^"]*)"([^}]*)\}', text[start:end + 1]):
            extra = m.group(3)
            cate = re.search(r"LeCate:(\d+)", extra)
            kind = re.search(r'LeType:"([^"]*)"', extra)
            out.append({"GUID": m.group(1), "Name": m.group(2), "LeCate": int(cate.group(1)) if cate else None,
                        "LeType": kind.group(1) if kind else None})
        return out
    return []


def install(src: Path, dest: Path = DATA_DIR) -> dict:
    """Extract the model data and libraries from the installer / app folder `src` into `dest`."""
    src = Path(src)
    with tempfile.TemporaryDirectory() as tmp:
        asar = _find_asar(src, Path(tmp))
        new = Path(tmp) / "vendor"
        count = 0
        with open(asar, "rb") as f:
            for name, offset, size in asar_entries(asar):
                if not name.startswith(WANTED):
                    continue
                out = new / name[len("resources/"):]
                out.parent.mkdir(parents=True, exist_ok=True)
                f.seek(offset)
                out.write_bytes(f.read(size))
                count += 1
            library = _default_library(f, asar_entries(asar))
            if library:
                (new / "res/data/le/library.json").write_text(json.dumps(library, ensure_ascii=False, indent=0))
        if not (new / "device/modellist.json").is_file():
            raise ValueError("the installer has no keyboard model data (device/modellist.json)")
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(new, dest)
    models = json.loads((dest / "device/modellist.json").read_text(encoding="utf-8-sig"))
    return {"files": count, "models": len(models), "dir": dest}
