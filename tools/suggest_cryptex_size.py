#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Suggest a value for IDEVICERESTORE_CRYPTEX_SIZE_MIB.

Reads the real system cryptex size (Cryptex1,SystemOSSize) from the IPSW's
BuildManifest.plist. Optionally reads the space numbers from the
restore_<ECID>_<time>.log that idevicerestore wrote during a failed attempt
with the same IPSW, and computes a value tuned to your device.

Usage:
    python3 tools/suggest_cryptex_size.py <firmware.ipsw>
    python3 tools/suggest_cryptex_size.py <firmware.ipsw> --log restore_<ECID>_<time>.log
"""

import argparse
import plistlib
import re
import sys
import zipfile

# Declared size minus real size in the run that recovered the first device, an
# iPhone 15 Pro on 24A446 (6500 MiB declared for a 5752 MiB cryptex).
# Used when no log is given.
TESTED_OVERDECLARE_MIB = 748

# How far the declared size should push SpaceNeededForRestore past
# ContainerFreeSpace. The successful run exceeded it by about 154 MB.
TARGET_EXCESS_MB = 150

SIZE_LINE = re.compile(r"Size of Cryptex1,SystemOS is (\d+) MB")
SPACE_LINE = re.compile(r"SpaceNeededForRestore: (\d+) MB\s*ContainerFreeSpace: (\d+) MB")


def read_manifest(ipsw_path):
    """Return the BuildManifest.plist of an IPSW as a dict."""
    with zipfile.ZipFile(ipsw_path) as ipsw:
        return plistlib.loads(ipsw.read("BuildManifest.plist"))


def update_cryptex_sizes(manifest):
    """Return {device_class: Cryptex1,SystemOSSize in MiB} for the Update identities."""
    sizes = {}
    for identity in manifest.get("BuildIdentities", []):
        info = identity.get("Info", {})
        size = info.get("Cryptex1,SystemOSSize")
        if info.get("RestoreBehavior") == "Update" and size is not None:
            sizes[info.get("DeviceClass", "unknown")] = size
    return sizes


def read_space_numbers(log_path):
    """Return (declared_mib, needed_mb, free_mb) from the last space check in a restore log.

    restored logs the cryptex size it used, then the space check:
        ramrod_splat_get_total_cryptex_size: Size of Cryptex1,SystemOS is 5752 MB
        SpaceNeededForRestore: 6040 MB ContainerFreeSpace: 6634 MB
    """
    with open(log_path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    declared = None
    result = None
    for match in re.finditer(f"{SIZE_LINE.pattern}|{SPACE_LINE.pattern}", text):
        if match.group(1) is not None:
            declared = int(match.group(1))
        elif declared is not None:
            result = (declared, int(match.group(2)), int(match.group(3)))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Suggest a value for IDEVICERESTORE_CRYPTEX_SIZE_MIB.")
    parser.add_argument("ipsw", help="the signed IPSW you will restore with")
    parser.add_argument("--log", help="restore_*.log from a failed idevicerestore attempt with the same IPSW")
    args = parser.parse_args()

    manifest = read_manifest(args.ipsw)
    sizes = update_cryptex_sizes(manifest)
    if not sizes:
        sys.exit("No Update identity with Cryptex1,SystemOSSize in this IPSW. This fix does not apply to it.")

    products = ", ".join(manifest.get("SupportedProductTypes", []))
    print(f"IPSW: {products}, iOS {manifest.get('ProductVersion')} ({manifest.get('ProductBuildVersion')})")
    for device_class, size in sorted(sizes.items()):
        print(f"Real Cryptex1,SystemOSSize ({device_class}): {size} MiB")

    if args.log:
        numbers = read_space_numbers(args.log)
        if numbers is None:
            sys.exit(f"No 'SpaceNeededForRestore' line found in {args.log}.")
        declared, needed, free = numbers
        headroom = free - needed
        value = declared + headroom + TARGET_EXCESS_MB
        print(f"From the log: declared {declared} MiB, needed {needed} MB, free {free} MB "
              f"({headroom} MB headroom)")
    else:
        if len(sizes) > 1:
            sys.exit("This IPSW covers several device classes. Pass --log to pick the right one.")
        value = next(iter(sizes.values())) + TESTED_OVERDECLARE_MIB
        print(f"No log given: using +{TESTED_OVERDECLARE_MIB} MiB, the over-declaration that "
              "recovered the first device (iPhone 15 Pro, 24A446).")

    print()
    print(f"IDEVICERESTORE_CRYPTEX_SIZE_MIB={value}")


if __name__ == "__main__":
    main()
