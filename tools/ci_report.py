#!/usr/bin/env python3
"""
ci_report.py -- turn pytest's JUnit XML into GitHub annotations.

    python tools/ci_report.py junit.xml "pytest ubuntu-latest py3.13"

Why: a session in the cloud can read the GitHub API (and so the annotations of a
job) but not the blob storage GitHub serves raw logs from. Without this, "CI is
green" would be all a session could ever know -- not how many tests ran, and not
which one failed. So each test job ends by publishing:

- one `notice` annotation whose title is the label given on the command line and
  whose message is the count: "34 passed, 0 failed, 0 errors, 2 skipped (36)";
- one `error` annotation per failing or erroring test, with the first line of
  the failure message.

`tools/ci_status.py` reads them back. Always exits 0: the pytest step has
already failed the job if something failed; this step only reports.
Standard library only.
"""

import os
import sys
import xml.etree.ElementTree as ET


def _escape(text):
    # GitHub workflow-command escaping for the message part.
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_prop(text):
    return _escape(text).replace(":", "%3A").replace(",", "%2C")


def summarise(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = failed = errors = skipped = 0
    problems = []
    for suite in suites:
        for case in suite.iter("testcase"):
            total += 1
            name = "%s::%s" % (case.get("classname", "?"), case.get("name", "?"))
            if case.find("failure") is not None:
                failed += 1
                node = case.find("failure")
                problems.append((name, (node.get("message") or node.text or "").strip()))
            elif case.find("error") is not None:
                errors += 1
                node = case.find("error")
                problems.append((name, (node.get("message") or node.text or "").strip()))
            elif case.find("skipped") is not None:
                skipped += 1
    passed = total - failed - errors - skipped
    line = "%d passed, %d failed, %d errors, %d skipped (%d)" % (
        passed, failed, errors, skipped, total)
    return line, problems


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 0
    path, label = argv
    if not os.path.exists(path):
        print("::error title=%s::no JUnit report at %s - pytest did not run"
              % (_escape_prop(label), _escape(path)))
        return 0
    line, problems = summarise(path)
    print("::notice title=%s::%s" % (_escape_prop(label), _escape(line)))
    for name, message in problems[:40]:
        first = message.splitlines()[0] if message else "(no message)"
        print("::error title=%s::%s: %s" % (_escape_prop(label), _escape(name),
                                            _escape(first[:300])))
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
