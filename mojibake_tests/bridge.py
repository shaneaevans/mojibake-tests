"""Long-lived subprocess workers, so a reader can be written in a language that is not Python, or
run in a Python process of its own.

The bench calls every reader once per case, and paying JVM or Node startup per cell turns a sweep
into a coffee break — so each runtime is spawned once and spoken to over a line protocol:

    ->  {"id": 7, "stack": "jsoup(bytes)", "ctype": ..., "body": <base64>, "sel": "#t::text"}
    <-  @@ENC@@{"id": 7, "values": [...]}          or  @@ENC@@{"id": 7, "error": "Type: message"}

Two things that protocol is deliberately built for:

- **The `@@ENC@@` prefix.** These libraries talk: Crawlee logs to stdout, jsdom reports parse
  errors. A protocol that shares a channel with library chatter eventually reports the chatter as
  an answer, so every reply is marked and every unmarked line is discarded.
- **The `id`.** Replies are checked against the request they answer. The JS worker's handlers are
  async, and a fire-and-forget listener replies in COMPLETION order — which silently permutes the
  columns of a sweep rather than failing it.

A worker that cannot start is not fatal: it reports `ERR:` per cell, because a bench that vanishes when a runtime is missing hides the ratio it
is there to report.
"""
import atexit
import base64
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = b"@@ENC@@"
TIMEOUT = 60.0          # a whole case, including JVM/jsdom warm-up on the first call


class Worker:
    """One long-lived interpreter answering extraction requests over stdin/stdout."""

    def __init__(self, name, argv, hint):
        self.name = name
        self.argv = argv
        self.hint = hint            # what to run when the runtime is not there
        self.proc = None
        self.dead = None            # the reason, once it is
        self.buf = b""
        self.next_id = 0
        self.errfile = None

    # ------------------------------------------------------------ lifecycle
    def start(self):
        if self.proc or self.dead:
            return
        if not shutil.which(self.argv[0]):
            self.dead = "%s not on PATH (%s)" % (self.argv[0], self.hint)
            return
        try:
            self.errfile = tempfile.TemporaryFile()
            self.proc = subprocess.Popen(self.argv, cwd=ROOT, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=self.errfile)
        except OSError as e:
            self.dead = "%s: %s (%s)" % (type(e).__name__, e, self.hint)
            return
        atexit.register(self.stop)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()

    def _die(self, why):
        """Record why the worker is unusable, with the first thing it said on stderr."""
        detail = ""
        if self.errfile:
            try:
                self.errfile.seek(0)
                first = self.errfile.read(4000).decode("utf-8", "replace").strip().splitlines()
                detail = ": " + first[0][:120] if first else ""
            except Exception:
                pass
        self.dead = "%s%s (%s)" % (why, detail, self.hint)
        if self.proc:
            self.proc.kill()
            self.proc = None

    # ------------------------------------------------------------ the protocol
    def _readline(self, deadline):
        """Read one line off the raw fd. Raw, because select() on the underlying descriptor and
        readline() on the buffered wrapper disagree about what has already arrived."""
        fd = self.proc.stdout.fileno()
        while b"\n" not in self.buf:
            left = deadline - time.time()
            if left <= 0:
                raise TimeoutError("no reply in %gs" % TIMEOUT)
            if not select.select([fd], [], [], left)[0]:
                raise TimeoutError("no reply in %gs" % TIMEOUT)
            chunk = os.read(fd, 65536)
            if not chunk:
                raise EOFError("worker exited")
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return line

    def request(self, payload):
        """Send one request, return the decoded reply dict, or None if the worker is unusable."""
        self.start()
        if self.dead:
            return None
        self.next_id += 1
        rid = self.next_id
        payload = dict(payload, id=rid)
        try:
            self.proc.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
            self.proc.stdin.flush()
            deadline = time.time() + TIMEOUT
            while True:
                line = self._readline(deadline)
                if line.startswith(MARK):          # anything else is the library talking
                    reply = json.loads(line[len(MARK):].decode("utf-8"))
                    if reply.get("id") not in (rid, None):
                        raise ValueError("reply %r answers request %r" % (reply.get("id"), rid))
                    return reply
        except Exception as e:
            self._die("%s: %s" % (type(e).__name__, e))
            return None

    def stacks(self):
        """What this worker offers — used to check the bench against the worker, not a hardcode."""
        reply = self.request({"op": "stacks"})
        return reply.get("stacks", []) if reply else []

    def call(self, stack, ctype, body, sel):
        """One extraction. Returns the values, or a one-element `ERR:` list — never raises, because
        a stack that refuses is an answer and has to reach the matrix."""
        reply = self.request({"stack": stack, "ctype": ctype, "sel": sel,
                              "body": base64.b64encode(body).decode("ascii")})
        if reply is None:
            return ["ERR:%s worker unavailable: %s" % (self.name, self.dead)]
        if "error" in reply:
            kind, _, msg = reply["error"].partition(": ")
            return ["ERR:%s: %s" % (kind, msg[:70])]
        return reply["values"]


JS = Worker("node", ["node", "js/reader.js"], hint="make js-bootstrap")
# Python again, but its own process: the readers that import frostwork.encoding, which registers
# process-wide codecs (readers._check_codec_registry).
FROSTWORK_WORKER_ENV = "MOJIBAKE_TESTS_FROSTWORK_WORKER"
FROSTWORK_PY = Worker("python", [sys.executable, "-m", "mojibake_tests.py_worker"], hint="make py-bootstrap")
JAVA = Worker("java", ["java", "-cp", "java/lib/*:java/build", "Reader"], hint="make java-bootstrap")
