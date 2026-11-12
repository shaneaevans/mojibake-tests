"""`python -m mojibake_tests.pinned_sweep` measures stacks at versions other than requirements.txt.

The bench pins the latest release of everything, but many scrapers run older ones. Scrapy 2.19.0
accepts any w3lib from 2.1.1 up, so on a real machine it can be running w3lib 2.4.1, which reads a
commented-out <meta charset> as a declaration. Scrapy 2.20.0 requires w3lib 2.6.0 and Frostwork, so
upgrading Scrapy now upgrades the encoding decision with it; the old pairs live on only where Scrapy
itself is held back. Each of those is a stack people really run, so each gets a column of its own:
the last Scrapy before Frostwork on the w3lib it shipped against, and on the older one.

Each pinned stack installs its old packages with --no-deps into `.pinned/<id>/`, which sits ahead
of the venv on sys.path, and runs an ordinary reader from readers.py in a subprocess. The
subprocess reports the version it actually imported. If that version isn't the pinned one, the
run fails: a column labelled w3lib 2.4.1 that quietly loaded 2.5.0 would be measuring the wrong
thing.

One stack is newer than any release: Frostwork as built in its own checkout. That one is imported
straight from the checkout's `python/` directory, never installed into the venv, because installing
it would also change the Frostwork that Scrapy decides encodings with. Its label comes from git:
the checkout's `frostwork.__version__` reads the installed release's metadata, so it says 0.2.2.
"""
import json
import os
import subprocess
import sys

from mojibake_tests.cases import CASES, fingerprint
from mojibake_tests.report import ROOT

OUT = os.path.join(ROOT, "results", "pinned-stacks.json")
FROSTWORK_CHECKOUT = os.environ.get("FROSTWORK_CHECKOUT", os.path.join(os.path.dirname(ROOT), "frostwork"))
CACHE = os.path.join(ROOT, ".pinned")

PINNED = [
    {
        "id": "scrapy+w3lib-2.4.1",
        "reader": "scrapy",
        "packages": {"scrapy": "2.19.0", "w3lib": "2.4.1"},
        "label": "Scrapy {scrapy} with w3lib {w3lib}",
        "how": "HtmlResponse(...).css(), on a w3lib that Scrapy 2.19 still accepts",
    },
    {
        "id": "scrapy-2.19.0",
        "reader": "scrapy",
        "packages": {"scrapy": "2.19.0", "w3lib": "2.5.0"},
        "label": "Scrapy {scrapy} with w3lib {w3lib}",
        "how": "HtmlResponse(...).css(), the last Scrapy whose encoding decision is w3lib's own",
    },
    # The bench's `frostwork` column is the release that Scrapy 2.20 depends on. The checkout is ahead
    # of it: the browser tree-builder, among other things, is in no release yet.
    {
        "id": "frostwork-checkout",
        "reader": "frostwork",
        "checkout": FROSTWORK_CHECKOUT,
        "packages": {"frostwork": None},
        "label": "Frostwork {frostwork} (unreleased)",
        "how": "frostwork.extract(), one streaming pass over the bytes, built from the checkout",
    },
]

CHILD = r"""
import importlib, json, os, sys
sys.path.insert(0, sys.argv[1])
# One reader per process, so the Frostwork family runs here rather than in a worker that would not
# see the pinned packages.
os.environ["MOJIBAKE_TESTS_FROSTWORK_WORKER"] = "1"
reader, packages = sys.argv[2], json.loads(sys.argv[3])
from mojibake_tests.cases import CASES
from mojibake_tests.readers import READERS
fn = dict(READERS)[reader]
loaded = {}
for p in packages:
    m = importlib.import_module(p)
    loaded[p] = getattr(m, "__version__", None) or importlib.metadata.version(p)
    loaded[p + "_file"] = m.__file__
cells = {}
for c in CASES:
    try:
        cells[c["id"]] = fn(c["ctype"], c["body"], c["sel"])
    except Exception as e:
        cells[c["id"]] = ["ERR:%s: %s" % (type(e).__name__, str(e).splitlines()[0][:80] if str(e) else "")]
print(json.dumps({"loaded": loaded, "cells": cells}, ensure_ascii=False))
"""


def _git(path, *args):
    return subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True,
                          check=True).stdout.strip()


def checkout_version(path):
    """`<branch> at <commit>`, refusing a dirty tree or a build older than its sources."""
    if _git(path, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("FAIL %s has uncommitted changes; commit or stash them first" % path)
    so = [f for f in os.listdir(os.path.join(path, "python", "frostwork")) if f.endswith(".so")]
    if not so:
        raise SystemExit("FAIL no built extension in %s/python/frostwork; run maturin there" % path)
    built = os.path.getmtime(os.path.join(path, "python", "frostwork", so[0]))
    for d in ("src", "Cargo.toml", "Cargo.lock"):
        for root, _, files in os.walk(os.path.join(path, d)) if os.path.isdir(os.path.join(path, d)) \
                else [(path, None, [d])]:
            for f in files:
                if os.path.getmtime(os.path.join(root, f)) > built:
                    raise SystemExit("FAIL %s is newer than the built extension; rebuild it"
                                     % os.path.join(root, f))
    return "%s at %s" % (_git(path, "rev-parse", "--abbrev-ref", "HEAD"),
                         _git(path, "rev-parse", "--short", "HEAD"))


def install(stack):
    if "checkout" in stack:
        return os.path.join(stack["checkout"], "python")
    target = os.path.join(CACHE, stack["id"])
    specs = ["%s==%s" % kv for kv in stack["packages"].items()]
    if not os.path.isdir(target):
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "--target", target]
                       + specs, check=True)
    return target


def main():
    by_id = {c["id"]: c for c in CASES}
    out, failed = {}, False
    try:
        with open(OUT, encoding="utf-8") as f:
            previous = json.load(f)
    except FileNotFoundError:
        previous = {}
    for stack in PINNED:
        if "checkout" in stack and not os.path.isdir(os.path.join(stack["checkout"], "python", "frostwork")):
            # Without a checkout there is nothing to measure. Keep the recorded column, whose cell
            # fingerprints still stop it being graded against bytes it was not measured on.
            print("SKIP %s: no Frostwork checkout at %s (set FROSTWORK_CHECKOUT); keeping the recorded column"
                  % (stack["id"], stack["checkout"]))
            if stack["id"] in previous:
                out[stack["id"]] = previous[stack["id"]]
            continue
        target = install(stack)
        res = subprocess.run([sys.executable, "-c", CHILD, target, stack["reader"],
                              json.dumps(stack["packages"])],
                             cwd=ROOT, capture_output=True, text=True, check=True)
        got = json.loads(res.stdout.strip().splitlines()[-1])
        loaded = got["loaded"]
        for pkg, want in stack["packages"].items():
            if (want is not None and loaded[pkg] != want) or not loaded[pkg + "_file"].startswith(target):
                print("FAIL %s: wanted %s %s, imported %s from %s"
                      % (stack["id"], pkg, want, loaded[pkg], loaded[pkg + "_file"]))
                failed = True
        missing = [c["id"] for c in CASES if c["id"] not in got["cells"]]
        if missing:
            print("FAIL %s answered %d of %d cases" % (stack["id"], len(CASES) - len(missing), len(CASES)))
            failed = True
        versions = {k: v for k, v in loaded.items() if not k.endswith("_file")}
        if "checkout" in stack:
            versions["frostwork"] = checkout_version(stack["checkout"])
        out[stack["id"]] = {
            "label": stack["label"].format(**versions),
            "versions": versions,
            "reader": stack["reader"],
            "how": stack["how"],
            "unreleased": "checkout" in stack,
            "cells": {cid: {"values": v, "sha": fingerprint(by_id[cid])} for cid, v in got["cells"].items()},
        }
        print("swept %s: %s" % (stack["id"], out[stack["id"]]["label"]))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("{\n" + ",\n".join("%s: %s" % (json.dumps(k), json.dumps(v, ensure_ascii=False))
                                    for k, v in out.items()) + "\n}\n")
    print("wrote %d stacks to %s" % (len(out), OUT))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
