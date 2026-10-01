"""Collect only compatible wheel archives for exact existing lock pins, locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from email.parser import Parser
from pathlib import Path

from pip._vendor.packaging.tags import parse_tag, sys_tags
from pip._vendor.packaging.utils import canonicalize_name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    args = parser.parse_args()
    pins = dict(line.strip().split("==") for line in args.lock.read_text().splitlines()
                if line.strip() and not line.startswith("#"))
    wanted = {canonicalize_name(name): version for name, version in pins.items()}
    supported = set(sys_tags())
    found = {}
    for source in args.cache.rglob("*.body"):
        try:
            with zipfile.ZipFile(source) as archive:
                names = archive.namelist()
                metadata_path = next((name for name in names if name.endswith(".dist-info/METADATA")),
                                     None)
                if metadata_path is None:
                    continue
                metadata = Parser().parsestr(archive.read(metadata_path).decode("utf-8"))
                name, version = canonicalize_name(metadata["Name"]), metadata["Version"]
                if wanted.get(name) != version or name in found:
                    continue
                wheel_path = metadata_path.rsplit("/", 1)[0] + "/WHEEL"
                wheel = Parser().parsestr(archive.read(wheel_path).decode("utf-8"))
                tags = wheel.get_all("Tag", [])
                tag = next((tag for tag in tags if set(parse_tag(tag)) & supported), None)
                if tag is None:
                    continue
                # Check archive integrity before admitting it to this batch wheelhouse.
                if archive.testzip() is not None:
                    continue
                found[name] = (source, f"{name.replace('-', '_')}-{version}-{tag}.whl")
        except (zipfile.BadZipFile, OSError, KeyError, UnicodeDecodeError):
            continue
    missing = sorted(set(wanted) - set(found))
    if missing:
        print(json.dumps({"missing_pins": missing, "collected": 0}))
        return 1
    args.destination.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, (source, filename) in sorted(found.items()):
        target = args.destination / filename
        if target.exists():
            raise ValueError("refusing to overwrite an existing cached wheel")
        shutil.copyfile(source, target)
        entries.append({"name": name, "version": wanted[name], "wheel": filename,
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    print(json.dumps({"source": "existing local pip HTTP cache, compatible wheel archives only",
                      "missing_pins": [], "wheels": entries}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
