#!/usr/bin/env python3
"""Apply a patch from the update workflow's low-trust build job.

Refuses anything other than regular files directly under the published data
paths. Checks git's index after applying, where paths and modes are canonical,
and compares raw bytes so locale and encoding cannot hide an entry.
Standard library only: this runs in the job that holds the write token.
"""

import re
import subprocess
import sys

ALLOWED_PATH = re.compile(rb"(?:(?:CSV|JSON|YAML)/[A-Za-z0-9][A-Za-z0-9._-]*|rtp\.json|rtp\.yaml)")
DATA_PATHS = ["CSV", "JSON", "YAML", "rtp.json", "rtp.yaml"]
REGULAR_FILE = b"100644"


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, stdout=subprocess.PIPE).stdout


def records(output: bytes) -> list[bytes]:
    return [record for record in output.split(b"\0") if record]


def main(patch: str) -> int:
    # --index records every touched path and its mode in the index, including ignored paths.
    # core.symlinks=false makes git write link text as a regular file instead of a symlink.
    git("-c", "core.symlinks=false", "apply", "--index", patch)

    unexpected = [path for path in records(git("diff", "--cached", "--name-only", "--no-renames", "-z"))
                  if not ALLOWED_PATH.fullmatch(path)]
    bad_modes = []
    for record in records(git("ls-files", "-s", "-z", "--", *DATA_PATHS)):
        meta, _, path = record.partition(b"\t")
        if meta.split(b" ", 1)[0] != REGULAR_FILE:
            bad_modes.append(record)

    if unexpected:
        print(f"::error::patch touches unexpected paths: {[repr(p) for p in unexpected]}")
    if bad_modes:
        print(f"::error::non-regular file modes: {[repr(r) for r in bad_modes]}")
    if unexpected or bad_modes:
        return 1

    git("reset", "-q")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: apply_data_patch.py PATCH")
    sys.exit(main(sys.argv[1]))
