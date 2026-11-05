"""Explicit diagnostics modes for the frozen build; never act on user music."""
import io
import sys
import unittest
from pathlib import Path
from music_core import ROOT, atomic_json


def run():
    if "--tag-self-test" in sys.argv:
        # Package and execute the real integration/rollback/resume test suite.
        import test_music_tags
        import test_pipeline
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
                                   for module in (test_music_tags, test_pipeline))
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        report = {"frozen": bool(getattr(sys, "frozen", False)), "root": str(ROOT),
                  "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                  "output": stream.getvalue(), "success": result.wasSuccessful()}
        atomic_json(Path(sys.argv[sys.argv.index("--tag-self-test") + 1]), report)
        if not result.wasSuccessful():
            raise RuntimeError(stream.getvalue())
    else:
        from music_matching import Matcher, lyric_text
        local = {"title": "Nuedori", "artist": "Suara",
                 "album": "Utawarerumono Itsuwarino Kamen and Futari No Hakuoro Kasyu", "duration": 300}
        match = Matcher(country="gb").match(local)
        meta, lyric = match.get("metadata") or {}, match.get("lyric") or {}
        text, kind = lyric_text(lyric)
        # Do not record the actual lyric text in diagnostic reports.
        report = {"frozen": bool(getattr(sys, "frozen", False)), "root": str(ROOT),
                  "metadata": {k: meta.get(k) for k in ("title", "artist", "score", "ready")},
                  "lyrics": {"kind": kind, "lines": len(text.splitlines()), "ready": lyric.get("ready")},
                  "errors": match.get("errors"), "success": bool(meta.get("ready") and text and lyric.get("ready"))}
        atomic_json(Path(sys.argv[sys.argv.index("--online-match-test") + 1]), report)
        if not report["success"]:
            raise RuntimeError("Online match diagnostic incomplete; see report")
