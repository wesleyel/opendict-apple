#!/usr/bin/env python3
"""Download pronunciation audio for every headword in the distribution artifact.

Dictionary.app's entry WebView has no outbound network access — remote <audio>
fails with MEDIA_ERR_SRC_NOT_SUPPORTED — so audio has to ship inside the bundle.
This fetches it once, into the layout `build_dict.sh` copies verbatim:

    <out>/OtherResources/Audio/<shard>/<slug>-<hash>_<uk|us>.mp3
    <out>/manifest.tsv    headword \\t uk path \\t us path   (empty field = no clip)
    <out>/misses.txt      headwords the source has no recording for

Everything under `OtherResources/` lands in `Contents/Resources/`, and nothing
else does — the bookkeeping sits deliberately outside it, because the DDK copies
that directory wholesale and a 7 MB manifest has no business in a user's bundle.

The manifest is the contract with src/build_appledict.py: only headwords listed
there get a play button, so a missing clip is a missing button rather than a
dead link. Roughly a third of upstream headwords have no recording at all —
multi-word phrases and hyphenated compounds mostly — and the source answers
those with a deterministic HTTP 500.

Usage:
  python3 scripts/fetch_audio.py distribution.jsonl.gz --out audio_files
  python3 scripts/fetch_audio.py distribution.jsonl.gz --out audio_files --limit 200
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# type=1 is British, type=2 American. Keyed by the word itself, not by IPA.
SOURCE = "https://dict.youdao.com/dictvoice?audio={word}&type={type}"
ACCENTS = {"uk": 1, "us": 2}
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) opendict-apple/1.0"

# A clip that small is an error page or silence, not a recording.
MIN_BYTES = 512

# Handed to the DDK as-is; see the module docstring for why it is a subdirectory.
BUNDLE_SUBDIR = "OtherResources"

_SLUG_BAD = re.compile(r"[^a-z0-9]+")


def open_maybe_gzip(path: str) -> io.TextIOBase:
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    return open(path, encoding="utf-8")


def rel_path(headword: str, accent: str) -> str:
    """Bundle-relative path for one clip.

    The slug alone is not enough: it lowercases, so `US` and `us` would collide
    on a case-insensitive volume, and it truncates. The hash of the exact
    headword disambiguates, and its first byte shards the tree so no directory
    holds more than a few hundred of the ~110k files.
    """
    digest = hashlib.sha1(headword.encode("utf-8")).hexdigest()[:8]
    slug = _SLUG_BAD.sub("_", headword.lower()).strip("_")[:32] or "w"
    return f"Audio/{digest[:2]}/{slug}-{digest}_{accent}.mp3"


def headwords(path: str, limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    with open_maybe_gzip(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                hw = json.loads(line).get("headword")
            except json.JSONDecodeError:
                continue
            if not isinstance(hw, str):
                continue
            hw = hw.strip()
            # Same rule the converter uses to decide an entry is renderable.
            if not hw or not any(c.isalnum() for c in hw) or hw in seen:
                continue
            seen.add(hw)
            out.append(hw)
            if limit and len(out) >= limit:
                break
    return out


def fetch_one(url: str, timeout: int, retries: int) -> bytes | None:
    """Returns the clip, or None when the source has no recording for it.

    A 500 here is the source's way of saying "no such recording" and repeats
    forever, so it is not retried. Transient failures — timeouts, resets, 429,
    503 — are, with a widening pause.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            return body if len(body) >= MIN_BYTES else None
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries:
                time.sleep(2 ** attempt + 1)
                continue
            return None
        except Exception:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("input", help="distribution.jsonl or distribution.jsonl.gz")
    ap.add_argument("--out", default="audio_files", help="staging root (default: audio_files)")
    ap.add_argument("--accents", default="uk,us", help="comma separated: uk, us (default: both)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N headwords")
    ap.add_argument("--workers", type=int, default=8, help="concurrent requests (default: 8)")
    ap.add_argument("--delay", type=float, default=0.05, help="pause per request, per worker")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--retries", type=int, default=2, help="retries for transient failures")
    ap.add_argument(
        "--retry-misses",
        action="store_true",
        help="re-request headwords previously recorded as having no clip",
    )
    args = ap.parse_args()

    accents = [a.strip() for a in args.accents.split(",") if a.strip()]
    bad = [a for a in accents if a not in ACCENTS]
    if bad:
        print(f"unknown accent(s): {', '.join(bad)}", file=sys.stderr)
        return 2

    out = args.out
    os.makedirs(out, exist_ok=True)
    manifest_path = os.path.join(out, "manifest.tsv")
    misses_path = os.path.join(out, "misses.txt")

    # Resume: a run over 110k files gets interrupted, and re-requesting what we
    # already hold is both slow and rude to the source.
    done: dict[str, dict[str, str]] = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            for row in fh:
                parts = row.rstrip("\n").split("\t")
                if len(parts) == 3 and parts[0]:
                    done[parts[0]] = {"uk": parts[1], "us": parts[2]}
    misses: set[str] = set()
    if os.path.exists(misses_path) and not args.retry_misses:
        with open(misses_path, encoding="utf-8") as fh:
            misses = {r.rstrip("\n") for r in fh if r.strip()}

    words = headwords(args.input, args.limit)
    todo = [w for w in words if w not in done and w not in misses]
    print(
        f"{len(words)} headwords: {len(done)} already fetched, {len(misses)} known misses, "
        f"{len(todo)} to go ({', '.join(accents)})",
        file=sys.stderr,
    )
    if not todo:
        print("nothing to do", file=sys.stderr)
        return 0

    lock = threading.Lock()
    counters = {"clips": 0, "bytes": 0, "words": 0, "empty": 0}

    def work(word: str) -> tuple[str, dict[str, str]]:
        got: dict[str, str] = {a: "" for a in ACCENTS}
        for accent in accents:
            rel = rel_path(word, accent)  # bundle-relative, as the manifest records it
            dest = os.path.join(out, BUNDLE_SUBDIR, rel)
            if os.path.exists(dest) and os.path.getsize(dest) >= MIN_BYTES:
                got[accent] = rel
                continue
            url = SOURCE.format(word=urllib.parse.quote(word, safe=""), type=ACCENTS[accent])
            body = fetch_one(url, args.timeout, args.retries)
            if args.delay:
                time.sleep(args.delay)
            if body is None:
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".part"
            with open(tmp, "wb") as fh:
                fh.write(body)
            os.replace(tmp, dest)  # never leave a half-written clip behind
            got[accent] = rel
            with lock:
                counters["clips"] += 1
                counters["bytes"] += len(body)
        return word, got

    started = time.time()
    with open(manifest_path, "a", encoding="utf-8") as mf, \
         open(misses_path, "a", encoding="utf-8") as xf, \
         cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for word, got in ex.map(work, todo):
            counters["words"] += 1
            if any(got.values()):
                mf.write(f"{word}\t{got['uk']}\t{got['us']}\n")
            else:
                counters["empty"] += 1
                xf.write(word + "\n")
            if counters["words"] % 500 == 0:
                mf.flush()
                xf.flush()
                rate = counters["words"] / max(time.time() - started, 1)
                left = (len(todo) - counters["words"]) / max(rate, 0.01) / 60
                print(
                    f"  … {counters['words']}/{len(todo)} words "
                    f"{counters['clips']} clips {counters['bytes'] / 1024**3:.2f} GB "
                    f"{rate:.1f}/s ~{left:.0f} min left",
                    file=sys.stderr,
                )

    print(
        f"fetched {counters['clips']} clips ({counters['bytes'] / 1024**3:.2f} GB) for "
        f"{counters['words'] - counters['empty']} headwords; "
        f"{counters['empty']} had no recording -> {manifest_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
