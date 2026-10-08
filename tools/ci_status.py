#!/usr/bin/env python3
"""
ci_status.py -- read CI yourself. Never assume green.

    python tools/ci_status.py                 the run for HEAD: every job, and
                                              the test counts each job published
    python tools/ci_status.py --wait 900      poll until it finishes (max seconds)
    python tools/ci_status.py --sha abc1234   a specific commit
    python tools/ci_status.py renders         fetch the pictures CI drew for HEAD
                                              into out/ci-renders/, to look at

Exit codes: 0 every job succeeded, 1 something failed or was cancelled,
3 still running (or no run found yet), 4 the API could not be reached.

How it reaches GitHub. Only the GitHub REST API and git are used, because that
is what a cloud session can reach (the blob storage behind raw logs and artefact
downloads is not). The per-job test counts come from the annotations that
tools/ci_report.py publishes; the pictures come from the `ci-renders` branch the
render job pushes on every commit to main. Public repository, so no token is
needed; if GITHUB_TOKEN is set it is sent, never printed.

Standard library only.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("PROMAK_GH_REPO", "nasdomak/promak")
API = "https://api.github.com/repos/" + REPO


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True)


def api(path):
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "promak-ci-status"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def head_sha():
    out = git("rev-parse", "HEAD")
    if out.returncode != 0:
        raise SystemExit("not a git checkout: %s" % out.stderr.strip())
    return out.stdout.strip()


def latest_run(sha):
    runs = api("/actions/runs?head_sha=%s&per_page=20" % sha).get("workflow_runs", [])
    runs = [r for r in runs if r.get("event") == "push"] or runs
    return runs[0] if runs else None


def report(sha):
    run = latest_run(sha)
    if not run:
        print("no CI run found for %s yet" % sha[:10])
        return 3, None
    print("run %s  %s  commit %s  status=%s  conclusion=%s"
          % (run["id"], run["name"], sha[:10], run["status"], run["conclusion"]))
    print("  %s" % run["html_url"])
    jobs = api("/actions/runs/%s/jobs?per_page=100" % run["id"]).get("jobs", [])
    worst = 0
    for job in sorted(jobs, key=lambda j: j["name"]):
        if job["status"] != "completed" and run["status"] == "completed":
            # Seen 02/10/2026: the jobs list kept one job "in_progress" for
            # minutes after the run (and the job's own check run) had completed.
            # The check run is the authoritative record; ask it.
            try:
                check = api("/check-runs/%s" % job["id"])
                job = dict(job, status=check["status"], conclusion=check["conclusion"])
            except urllib.error.HTTPError:
                pass
        verdict = job["conclusion"] or job["status"]
        print("  %-34s %s" % (job["name"], verdict))
        if job["status"] != "completed":
            worst = max(worst, 3) if worst != 1 else 1
        elif job["conclusion"] not in ("success", "skipped"):
            worst = 1
            for step in job.get("steps", []):
                if step.get("conclusion") == "failure":
                    print("      failed step: %s" % step["name"])
        if job["status"] == "completed":
            try:
                notes = api("/check-runs/%s/annotations" % job["id"])
            except urllib.error.HTTPError:
                notes = []
            for n in notes:
                if n.get("title", "").startswith("pytest"):
                    level = "ERROR" if n["annotation_level"] == "failure" else "tests"
                    print("      %s: %s" % (level, n["message"]))
    if run["status"] != "completed" and worst == 0:
        worst = 3
    return worst, run


def fetch_renders(sha, dest):
    got = git("fetch", "-q", "origin", "ci-renders")
    if got.returncode != 0:
        print("could not fetch ci-renders: %s" % got.stderr.strip())
        return 1
    source = git("show", "FETCH_HEAD:SOURCE_SHA")
    drawn_for = source.stdout.strip()
    if drawn_for != sha:
        print("ci-renders holds pictures of %s, not of %s: CI has not finished "
              "the render job for this commit yet" % (drawn_for[:10], sha[:10]))
        return 3
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    names = git("ls-tree", "--name-only", "FETCH_HEAD").stdout.split()
    for name in names:
        blob = subprocess.run(["git", "show", "FETCH_HEAD:" + name], cwd=ROOT,
                              stdin=subprocess.DEVNULL, capture_output=True)
        with open(os.path.join(dest, name), "wb") as fh:
            fh.write(blob.stdout)
    print("pictures CI drew for %s:" % sha[:10])
    for name in names:
        print("  %s" % os.path.relpath(os.path.join(dest, name), ROOT))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", default="status", choices=["status", "renders"])
    ap.add_argument("--sha")
    ap.add_argument("--wait", type=int, default=0, help="seconds to poll for")
    ap.add_argument("--dest", default=os.path.join(ROOT, "out", "ci-renders"))
    args = ap.parse_args(argv)
    sha = args.sha or head_sha()
    if len(sha) < 40:
        sha = git("rev-parse", sha).stdout.strip() or sha
    try:
        if args.what == "renders":
            return fetch_renders(sha, args.dest)
        deadline = time.time() + args.wait
        while True:
            code, _ = report(sha)
            if code != 3 or time.time() >= deadline:
                return code
            print("  ... still running, checking again in 30 s")
            time.sleep(30)
    except urllib.error.URLError as exc:
        print("GitHub API unreachable: %s" % exc)
        return 4


if __name__ == "__main__":
    sys.exit(main())
