#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Measure the largest single all-at-once preallocation APFS will grant.

The restore ramdisk reserves the whole system cryptex in one
fcntl(F_PREALLOCATE, F_ALLOCATEALL) call. This script shows that APFS refuses
such a call once it exceeds roughly 84% of the free space.

macOS only. It creates a throwaway APFS sparse disk image in a temporary
directory, binary-searches the largest grantable request, prints the result,
and deletes the image. Your own disks are not touched.

Usage:
    python3 tools/apfs_prealloc_ceiling.py [--size-gib 8]
"""

import argparse
import contextlib
import fcntl
import os
import struct
import subprocess
import sys
import tempfile

F_PREALLOCATE = 42
F_ALLOCATEALL = 0x4
F_PEOFPOSMODE = 3
FSTORE_T = "Iiqqq"  # fst_flags, fst_posmode, fst_offset, fst_length, fst_bytesalloc

MIB = 1024 * 1024
CRYPTEX_BYTES = 6_031_409_152  # iOS 27.0.1 (24A446) system cryptex, for comparison


def can_preallocate(path, length):
    """Return True if APFS grants a single all-at-once preallocation of `length` bytes."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_TRUNC)
    try:
        request = struct.pack(FSTORE_T, F_ALLOCATEALL, F_PEOFPOSMODE, 0, length, 0)
        fcntl.fcntl(fd, F_PREALLOCATE, request)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)
        os.unlink(path)


def free_bytes(mount):
    stats = os.statvfs(mount)
    return stats.f_bavail * stats.f_frsize


def largest_preallocation(mount):
    """Binary-search the largest grantable request, to within 1 MiB."""
    probe = os.path.join(mount, "probe")
    low, high = 0, free_bytes(mount)
    if can_preallocate(probe, high):
        return high
    while high - low > MIB:
        mid = (low + high) // 2
        if can_preallocate(probe, mid):
            low = mid
        else:
            high = mid
    return low


@contextlib.contextmanager
def scratch_apfs_volume(size_gib):
    """Create, mount, and afterwards remove a temporary APFS sparse image."""
    with tempfile.TemporaryDirectory() as tmp:
        image = os.path.join(tmp, "probe.sparseimage")
        mountpoint = os.path.join(tmp, "mnt")
        os.mkdir(mountpoint)
        subprocess.run(["hdiutil", "create", "-quiet", "-size", f"{size_gib}g", "-type", "SPARSE",
                        "-fs", "APFS", "-volname", "prealloc-probe", image], check=True)
        subprocess.run(["hdiutil", "attach", "-quiet", "-nobrowse", "-mountpoint", mountpoint, image],
                       check=True)
        try:
            yield mountpoint
        finally:
            subprocess.run(["hdiutil", "detach", "-quiet", "-force", mountpoint], check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--size-gib", type=int, default=8, help="size of the scratch image (default: 8)")
    args = parser.parse_args()

    if sys.platform != "darwin":
        sys.exit("This script needs macOS (APFS and hdiutil).")

    with scratch_apfs_volume(args.size_gib) as mount:
        free = free_bytes(mount)
        largest = largest_preallocation(mount)

    ratio = largest / free
    print(f"Free space:               {free:>15,} bytes ({free / MIB:,.0f} MiB)")
    print(f"Largest single request:   {largest:>15,} bytes ({largest / MIB:,.0f} MiB)")
    print(f"Ceiling:                  {ratio:.2%} of free space")
    print(f"A {CRYPTEX_BYTES / MIB:,.0f} MiB cryptex needs at least {CRYPTEX_BYTES / ratio / MIB:,.0f} MiB free.")


if __name__ == "__main__":
    main()
