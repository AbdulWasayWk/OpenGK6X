"""Minimal Electron .asar extractor.

usage: asar_extract.py <app.asar> <outdir>

Layout: u32 4, u32 header size, u32 pickle payload size, u32 JSON length, JSON tree, then file data from
8 + header size. File entries have "size" and "offset" (a string, relative to the data start); files marked
"unpacked" live next to the archive in <app.asar>.unpacked/ and are skipped here.
"""
import json, os, struct, sys

src, out = sys.argv[1], sys.argv[2]
with open(src, "rb") as f:
    _, header_size, _, json_len = struct.unpack("<4I", f.read(16))
    tree = json.loads(f.read(json_len))
    base = 8 + header_size
    count = skipped = 0

    def walk(node, path):
        global count, skipped
        for name, entry in node["files"].items():
            p = os.path.join(path, name)
            if "files" in entry:
                os.makedirs(p, exist_ok=True)
                walk(entry, p)
            elif "link" in entry or entry.get("unpacked"):
                skipped += 1
            else:
                f.seek(base + int(entry["offset"]))
                with open(p, "wb") as o:
                    o.write(f.read(entry["size"]))
                count += 1

    os.makedirs(out, exist_ok=True)
    walk(tree, out)
print(f"{count} files extracted, {skipped} links/unpacked skipped")
