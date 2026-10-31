#!/usr/bin/env python3
"""PROJEKT: TsukuraMedia - TGM Online-Bibliothek.

Validates every device folder, builds deterministic package ZIPs and index.json.
Python standard library only (no pip install, no C++ in the GitHub workflow).

Usage:
  build_index.py --repo owner/name --commit <sha> --out build [--devices-dir devices]
                 [--previous prev-index.json] [--tag packages] [--validate-only]
  build_index.py --self-test

Outputs (in --out):
  index.json            tgm.index/1
  packages/<m>-<d>-v<version>.zip
  changed.txt           ZIPs that are new or differ from --previous (one path per line)
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_IMAGE_BYTES = 2 * 1024 * 1024
ALLOWED_IMAGE_EXT = (".png", ".jpg")
FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
CDN = "https://cdn.jsdelivr.net/gh"


# ----------------------------------------------------------------------------
# Tiny JSON-Schema subset validator (type, const, enum, required, properties,
# items, pattern, minimum, maximum, minLength, maxLength, minItems, maxItems).
# ----------------------------------------------------------------------------
_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def validate(value, schema, path="$"):
    """Returns a list of error strings (empty = valid)."""
    errs = []
    if "const" in schema and value != schema["const"]:
        errs.append("%s: must be %r" % (path, schema["const"]))
        return errs
    if "enum" in schema and value not in schema["enum"]:
        errs.append("%s: not one of %r" % (path, schema["enum"]))
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in types):
            errs.append("%s: expected %s" % (path, "/".join(types)))
            return errs
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append("%s: shorter than %d" % (path, schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append("%s: longer than %d" % (path, schema["maxLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append("%s: does not match %s" % (path, schema["pattern"]))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append("%s: below %s" % (path, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errs.append("%s: above %s" % (path, schema["maximum"]))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errs.append("%s: missing '%s'" % (path, key))
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errs.extend(validate(value[key], sub, "%s.%s" % (path, key)))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append("%s: fewer than %d items" % (path, schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append("%s: more than %d items" % (path, schema["maxItems"]))
        if "items" in schema:
            for i, item in enumerate(value):
                errs.extend(validate(item, schema["items"], "%s[%d]" % (path, i)))
                if len(errs) > 50:
                    errs.append("... more errors suppressed")
                    return errs
    return errs


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_schema(name):
    return load_json(os.path.join(REPO_ROOT, "schema", name))


# ----------------------------------------------------------------------------
# Device folder handling
# ----------------------------------------------------------------------------
def find_device_dirs(devices_dir):
    """Yields (manufacturer_slug, device_slug, folder) sorted."""
    out = []
    if not os.path.isdir(devices_dir):
        return out
    for m in sorted(os.listdir(devices_dir)):
        mdir = os.path.join(devices_dir, m)
        if not os.path.isdir(mdir) or m.startswith("."):
            continue
        for d in sorted(os.listdir(mdir)):
            ddir = os.path.join(mdir, d)
            if os.path.isdir(ddir) and not d.startswith("."):
                out.append((m, d, ddir))
    return out


def folder_files(folder):
    """Relative posix paths of every file in a device folder, sorted."""
    files = []
    for root, _dirs, names in os.walk(folder):
        for n in names:
            full = os.path.join(root, n)
            files.append(os.path.relpath(full, folder).replace(os.sep, "/"))
    return sorted(files)


def validate_device(m, d, folder, schemas):
    """Returns (errors, device_json, panel_json_or_None)."""
    errs = []
    if not SLUG_RE.match(m) or not SLUG_RE.match(d):
        errs.append("folder name must be a slug (a-z0-9 and '-'): %s/%s" % (m, d))
    files = folder_files(folder)
    for rel in files:
        top = rel.split("/")[0]
        ok = (rel in ("device.json", "panel.json")
              or (top == "images" and rel.count("/") == 1 and rel.lower().endswith(ALLOWED_IMAGE_EXT)))
        if not ok:
            errs.append("file not allowed in a device folder: %s" % rel)
        elif top == "images" and os.path.getsize(os.path.join(folder, rel)) > MAX_IMAGE_BYTES:
            errs.append("image larger than 2 MB: %s" % rel)
    if "device.json" not in files:
        errs.append("device.json missing")
        return errs, None, None
    try:
        dev = load_json(os.path.join(folder, "device.json"))
    except (ValueError, OSError) as exc:
        errs.append("device.json unreadable: %s" % exc)
        return errs, None, None
    errs.extend("device.json " + e for e in validate(dev, schemas["device"]))
    if isinstance(dev, dict):
        if dev.get("id") != "%s/%s" % (m, d):
            errs.append("device.json id %r does not match folder %s/%s" % (dev.get("id"), m, d))
        if "scripts" in dev:
            errs.append("device.json must not contain scripts (online library = TGM device scripts only)")
        for key, rel in list(dev.get("images", {}).items()):
            if rel not in files:
                errs.append("device.json references missing file: %s" % rel)
    panel = None
    if "panel.json" in files:
        try:
            panel = load_json(os.path.join(folder, "panel.json"))
            errs.extend("panel.json " + e for e in validate(panel, schemas["panels"]))
        except (ValueError, OSError) as exc:
            errs.append("panel.json unreadable: %s" % exc)
    return errs, dev, panel


def build_zip(folder, zip_path):
    """Deterministic ZIP of the folder: sorted entries, fixed timestamps."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in folder_files(folder):
            info = zipfile.ZipInfo(rel, FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(folder, rel), "rb") as fh:
                zf.writestr(info, fh.read(), zipfile.ZIP_DEFLATED, 9)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_updated(folder, fallback):
    try:
        res = subprocess.run(["git", "log", "-1", "--format=%cI", "--", folder],
                             capture_output=True, text=True, timeout=30, cwd=folder)
        out = res.stdout.strip()
        if res.returncode == 0 and out:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    return fallback


def check_manufacturers(path, devices):
    """Light check of manufacturers.json; unknown manufacturers are only a warning."""
    warnings = []
    if not os.path.isfile(path):
        return ["manufacturers.json missing"], []
    try:
        data = load_json(path)
    except ValueError as exc:
        return ["manufacturers.json unreadable: %s" % exc], []
    errs = []
    if not isinstance(data, dict) or data.get("schema") != "tgm.manufacturers/1" \
            or not isinstance(data.get("manufacturers"), list):
        errs.append("manufacturers.json must be {schema:'tgm.manufacturers/1', manufacturers:[...]}")
        return errs, warnings
    known = set()
    for entry in data["manufacturers"]:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            known.add(entry["name"].strip().lower())
            for alias in entry.get("aliases", []) or []:
                known.add(str(alias).strip().lower())
    if known:
        for dev in devices:
            name = dev["manufacturer"]["name"].strip().lower()
            if name not in known:
                warnings.append("manufacturer not in manufacturers.json: %s" % dev["manufacturer"]["name"])
    return errs, warnings


def build(args):
    devices_dir = os.path.abspath(args.devices_dir)
    out_dir = os.path.abspath(args.out)
    pkg_dir = os.path.join(out_dir, "packages")
    os.makedirs(pkg_dir, exist_ok=True)
    schemas = {"device": load_schema("device.schema.json"),
               "panels": load_schema("panels.schema.json"),
               "index": load_schema("index.schema.json")}
    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    prev = {}
    if args.previous and os.path.isfile(args.previous):
        try:
            for e in load_json(args.previous).get("devices", []):
                prev[e["id"]] = e.get("packageSha256")
        except (ValueError, KeyError, AttributeError):
            prev = {}

    errors = []
    entries = []
    devices_loaded = []
    changed = []
    for m, d, folder in find_device_dirs(devices_dir):
        errs, dev, panel = validate_device(m, d, folder, schemas)
        if errs:
            errors.extend("%s/%s: %s" % (m, d, e) for e in errs)
            continue
        devices_loaded.append(dev)
        if args.validate_only:
            continue
        zip_name = "%s-%s-v%d.zip" % (m, d, dev["version"])
        zip_path = os.path.join(pkg_dir, zip_name)
        build_zip(folder, zip_path)
        sha = sha256_file(zip_path)
        base = "%s/%s@%s/devices/%s/%s" % (CDN, args.repo, args.commit, m, d)
        images = dev.get("images") or {}
        thumb = images.get("device") or images.get("panel")
        presets = dev.get("presets") or []
        cats = sorted({p["category"] for p in presets if isinstance(p.get("category"), str) and p["category"]})
        entry = {
            "id": dev["id"],
            "manufacturer": dev["manufacturer"]["name"],
            "name": dev["device"]["name"],
            "kind": dev["device"].get("kind"),
            "deviceType": dev["device"].get("deviceType"),
            "version": dev["version"],
            "updated": dev.get("updated") or git_updated(folder, generated),
            "presetCount": len(presets),
            "bankCount": len(dev.get("banks") or []),
            "hasPanel": bool(panel and panel.get("panels")),
            "categories": cats[:50],
            "description": (dev.get("description") or "")[:600],
            "thumbUrl": "%s/%s" % (base, thumb) if thumb else "",
            "packageUrl": "https://github.com/%s/releases/download/%s/%s" % (args.repo, args.tag, zip_name),
            "packageSha256": sha,
            "packageSize": os.path.getsize(zip_path),
        }
        entries.append(entry)
        if prev.get(dev["id"]) != sha:
            changed.append(zip_path)

    m_errs, m_warns = check_manufacturers(os.path.join(os.path.abspath(args.root), "manufacturers.json"),
                                          devices_loaded)
    errors.extend(m_errs)
    for w in m_warns:
        print("WARNING: " + w, file=sys.stderr)

    if errors:
        for e in errors:
            print("ERROR: " + e, file=sys.stderr)
        print("%d validation error(s)." % len(errors), file=sys.stderr)
        return 1
    if args.validate_only:
        print("OK: %d device(s) valid." % len(devices_loaded))
        return 0

    entries.sort(key=lambda e: e["id"])
    index = {"schema": "tgm.index/1", "generated": generated, "repo": args.repo, "devices": entries}
    idx_errs = validate(index, schemas["index"])
    if idx_errs:
        for e in idx_errs:
            print("ERROR: index.json " + e, file=sys.stderr)
        return 1
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    with open(os.path.join(out_dir, "changed.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(p + "\n" for p in changed))
    print("OK: %d device(s), %d changed package(s) -> %s" % (len(entries), len(changed), out_dir))
    return 0


def self_test():
    examples = os.path.join(REPO_ROOT, "examples")
    ns = argparse.Namespace(root=REPO_ROOT, devices_dir=examples, repo="example/tsukura-tgm-library",
                            commit="0123456789abcdef0123456789abcdef01234567", tag="packages",
                            previous=None, validate_only=False, out=None)
    with tempfile.TemporaryDirectory() as tmp:
        ns.out = os.path.join(tmp, "a")
        assert build(ns) == 0, "build failed"
        index = load_json(os.path.join(ns.out, "index.json"))
        assert len(index["devices"]) == 1, "expected 1 example device"
        dev = index["devices"][0]
        zpath = os.path.join(ns.out, "packages", "example-maker-example-device-v1.zip")
        assert os.path.isfile(zpath), "zip missing"
        assert sha256_file(zpath) == dev["packageSha256"], "sha mismatch"
        assert dev["packageSize"] == os.path.getsize(zpath), "size mismatch"
        names = zipfile.ZipFile(zpath).namelist()
        assert names == sorted(names) and "device.json" in names, "zip layout"
        assert dev["thumbUrl"].startswith(CDN + "/example/tsukura-tgm-library@0123456789abcdef"), "thumb url"
        assert dev["packageUrl"].endswith("/releases/download/packages/example-maker-example-device-v1.zip")
        assert dev["presetCount"] == 3 and dev["hasPanel"] is True and dev["categories"] == ["Bass", "Pad"]
        assert validate(index, load_schema("index.schema.json")) == [], "index schema"
        assert len(open(os.path.join(ns.out, "changed.txt")).read().split()) == 1, "changed.txt"
        # determinism + previous-index handling
        ns.out = os.path.join(tmp, "b")
        ns.previous = os.path.join(tmp, "a", "index.json")
        assert build(ns) == 0
        assert sha256_file(os.path.join(ns.out, "packages", "example-maker-example-device-v1.zip")) == dev["packageSha256"], \
            "zip is not deterministic"
        assert open(os.path.join(ns.out, "changed.txt")).read() == "", "unchanged package listed as changed"
        # negative probe: a broken device must fail validation
        bad = os.path.join(tmp, "bad", "m", "d")
        os.makedirs(bad)
        with open(os.path.join(bad, "device.json"), "w", encoding="utf-8") as fh:
            json.dump({"schema": "tgm.device/1", "id": "m/other", "version": 0}, fh)
        with open(os.path.join(bad, "evil.exe"), "wb") as fh:
            fh.write(b"MZ")
        errs, _dev, _panel = validate_device("m", "d", bad, {"device": load_schema("device.schema.json"),
                                                          "panels": load_schema("panels.schema.json")})
        assert len(errs) >= 4, "negative probe expected errors, got %r" % errs
    print("SELF-TEST OK")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=REPO_ROOT, help="repository root (manufacturers.json lives here)")
    ap.add_argument("--devices-dir", default=None, help="default: <root>/devices")
    ap.add_argument("--repo", default="", help="owner/name of the GitHub repository")
    ap.add_argument("--commit", default="main", help="commit SHA the CDN URLs are pinned to")
    ap.add_argument("--tag", default="packages", help="release tag that holds the packages")
    ap.add_argument("--out", default="build")
    ap.add_argument("--previous", default=None, help="previous index.json (to list changed packages)")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.devices_dir is None:
        args.devices_dir = os.path.join(args.root, "devices")
    if not args.validate_only and not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", args.repo):
        ap.error("--repo owner/name is required")
    return build(args)


if __name__ == "__main__":
    sys.exit(main())
