"""`python -m mojibake_tests.py_worker`: the Frostwork-family readers, in a process of their own.

They import frostwork.encoding, which registers Python codecs for the whole process
(readers._check_codec_registry says why that matters). This worker speaks bridge.py's line protocol,
the same one js/reader.js and java/Reader.java speak.
"""
import base64
import json
import os
import sys

os.environ["MOJIBAKE_TESTS_FROSTWORK_WORKER"] = "1"

from mojibake_tests.readers import FROSTWORK_FAMILY, READERS  # noqa: E402

MARK = "@@ENC@@"


def main():
    fns = {n: fn for n, fn in READERS if n in FROSTWORK_FAMILY}
    for line in sys.stdin:
        req = json.loads(line)
        rid = req.get("id")
        try:
            if req.get("op") == "stacks":
                reply = {"id": rid, "stacks": list(fns)}
            else:
                body = base64.b64decode(req["body"])
                reply = {"id": rid, "values": fns[req["stack"]](req["ctype"], body, req["sel"])}
        except Exception as e:
            reply = {"id": rid, "error": "%s: %s" % (type(e).__name__, e)}
        sys.stdout.write(MARK + json.dumps(reply, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
