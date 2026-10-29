# Fix an iPhone stuck in Recovery mode after an update failed on full storage, without erasing it

In September 2026 an iOS 27.0 update failed on my iPhone 15 Pro because its
storage was almost full (`Failed preallocation due to space`). After that there
was no working iOS left on the phone. It only started in Recovery mode, and
Apple's tools offered only **Erase**, which would have deleted all my photos.

I found a way to finish the update **without losing any data**. It uses a small
patch for [idevicerestore](https://github.com/libimobiledevice/idevicerestore)
and installs a normal, Apple-signed iOS update. This guide shows you how, so you
can try it on your own iPhone.

> **So far I've tested this on one device: my own** iPhone 15 Pro (`iPhone16,1`).
> I recovered it on iOS 27.0.1 (24A446) with all photos, apps and data intact.
> If you try this, please [report your result](https://github.com/3SENN/iphone-stuck-in-recovery-full-storage/issues/new?template=result.yml)
> so others know whether it works on their device.

**Contents:** [Does this apply to you?](#does-this-apply-to-you) ·
[Before you start](#before-you-start) · [What you need](#what-you-need) ·
[Steps](#steps) · [If it doesn't work](#if-it-doesnt-work) ·
[How it works](#how-it-works) · [Files](#files) · [License](#license) ·
[About](#about)

## Does this apply to you?

All three must be true:

1. A data-preserving **update** (not an erase) of the iPhone failed, and it now
   only starts in **Recovery mode**.
2. Retrying the update fails at the same step, with these lines in the
   idevicerestore output:

   ```
   Transfer: Failed preallocation of <N> bytes for /mnt9/cryptex1/current/os.dmg: Unknown error: -1.
   Transfer: Failed preallocation due to space. No hope in this succeeding, bailing.
   CHECKPOINT FAILURE:(FAILURE:100) install_splat [0]D(failed to install splat)
   ```

3. The phone was nearly full.

If you're not sure about point 2, step 4 below checks it for you. If the error is
different, this fix won't help.
[idevicerestore issue #734](https://github.com/libimobiledevice/idevicerestore/issues/734)
shows the same error.

## Before you start

- **Only use this on a phone you own or are authorized to restore.** It installs a
  normal, Apple-signed iOS update. It can't bypass a passcode, Activation Lock, or
  Apple's signing.
- **The phone deletes some data to make room.** This is how the fix works: it makes
  the phone run its built-in low-space cleanup. That cleanup clears caches and logs,
  can purge photo and mail data, and can remove apps. Most likely it only removes
  data iOS has marked as purgeable, but I can't confirm that. On my phone nothing
  was lost: all photos, apps and data were still there.
- **A failed attempt can be retried.** The update stops before it writes the
  cryptex, and the phone stays in Recovery mode.
- **Never add `-e` to the idevicerestore command.** `-e` erases the phone.

## What you need

- A Mac with [Homebrew](https://brew.sh) and the Xcode Command Line Tools
  (`xcode-select --install`). Tested on macOS 26. Linux should work with the
  libimobiledevice libraries built from source, but is untested.
- A good USB cable.
- An Apple-signed IPSW for your exact model, for the **same or a newer iOS
  version** than the update that failed. [ipsw.me](https://ipsw.me) shows which
  builds Apple still signs.
  - An older version won't work. The failed update already recorded the new
    version on the phone, and the update refuses to downgrade
    (`FAILURE:68 downgrade_check`).
- No other restore tool running at the same time (Finder restore, Apple
  Configurator, 3uTools). They take over the phone.

## Steps

### 1. Build the patched idevicerestore

```sh
brew install autoconf automake libtool pkgconf libimobiledevice libirecovery libtatsu libzip

git clone https://github.com/3SENN/iphone-stuck-in-recovery-full-storage.git
git clone https://github.com/libimobiledevice/idevicerestore.git
cd idevicerestore
git checkout 60192e9
git apply ../iphone-stuck-in-recovery-full-storage/patches/0001-restore-Allow-overriding-the-declared-Cryptex1-SystemOSSize.patch
./autogen.sh --prefix="$PWD/install"
make -j4 && make install
./install/bin/idevicerestore --version
```

`60192e9` is the upstream commit I used to recover my phone. The patch also
applies to newer commits. Run the remaining steps from this `idevicerestore`
folder.

> **iPhone 16 and newer: build libtatsu from source first.** The libtatsu 1.0.5
> release (what Homebrew installs) picks the wrong Face ID firmware component on
> newer IPSWs, so the restore stops with `Unable to fetch Yonkers ticket` before
> it reaches the storage step. The fix is upstream
> ([libtatsu `cdbca26`](https://github.com/libimobiledevice/libtatsu/commit/cdbca263fa480b118bd458e32c6eeddafd48e35d))
> but not released yet. From the `idevicerestore` folder, build it and rebuild
> idevicerestore against it:
>
> ```sh
> cd ..
> git clone https://github.com/libimobiledevice/libtatsu.git
> cd libtatsu
> ./autogen.sh --prefix="$PWD/install" --enable-static --disable-shared
> make -j4 && make install
> cd ../idevicerestore
> make distclean
> export PKG_CONFIG_PATH="$PWD/../libtatsu/install/lib/pkgconfig:$(brew --prefix)/lib/pkgconfig"
> ./autogen.sh --prefix="$PWD/install"
> make -j4 && make install
> ```
>
> `strings ./install/bin/idevicerestore | grep -x 'Yonkers,SysTopPatch'` prints
> a line when the newer libtatsu is in. Needed on an iPhone 16 Pro (`iPhone17,1`)
> with iOS 27.2 (24B119).

### 2. Check that the phone is in Recovery mode

```sh
irecovery -q | grep -E 'MODE|PRODUCT|ECID'
```

You should see `MODE: Recovery`, your model (for example `PRODUCT: iPhone16,1`),
and an `ECID: 0x…`. You'll use the ECID below.

### 3. Download the IPSW

Download the signed IPSW for the `PRODUCT` shown in step 2.

### 4. Run the update once without the fix

This checks that you have this exact problem, and records the space numbers that
step 5 needs:

```sh
caffeinate -is ./install/bin/idevicerestore -y -P -i <ECID> <firmware.ipsw>
```

It should fail with the `Failed preallocation due to space` error shown above.
idevicerestore saves a `restore_<ECID>_<time>.log` file in the current folder.

You can skip this step if you already have a log from a failed idevicerestore
attempt with the same IPSW.

### 5. Pick the size to declare

```sh
python3 ../iphone-stuck-in-recovery-full-storage/tools/suggest_cryptex_size.py <firmware.ipsw> --log restore_<ECID>_<time>.log
```

The last line is the value to use, for example `IDEVICERESTORE_CRYPTEX_SIZE_MIB=6500`.
Without `--log`, the tool adds 748 MiB to the real size, which is what worked on
my phone.

### 6. Run the update with the fix

```sh
IDEVICERESTORE_CRYPTEX_SIZE_MIB=<value> caffeinate -is ./install/bin/idevicerestore -y -P -i <ECID> <firmware.ipsw>
```

A successful run looks like this. The first line shows that the fix is active:

```
Declaring Cryptex1,SystemOSSize as 6500 MiB (real size 5752 MiB)
...
Sending Cryptex1,SystemOS now (2348810240 bytes)
Done sending Cryptex1,SystemOS
...
Sealing System Volume (77)
...
Status: Restore Finished
```

### 7. Let the phone start

The first start after the update can take 5 to 10 minutes. Enter your passcode
when the phone asks, and tap **Trust** if your Mac asks.

## If it doesn't work

| What you see | What to do |
|--------------|------------|
| The same `Failed preallocation` error | The value is probably too small to trigger the cleanup. If you didn't use `--log`, run step 5 with the new log. Otherwise raise the value by 200 and retry. |
| No `Declaring Cryptex1,SystemOSSize` line | The fix isn't active. Check that you ran `./install/bin/idevicerestore` and set the variable on the same command line. |
| `Unable to fetch Yonkers ticket` | libtatsu is too old for your IPSW. Build libtatsu from source as described in step 1, rebuild idevicerestore, and retry. |
| `FAILURE:68 downgrade_check` | The IPSW is older than the update that failed. Use the same or a newer version. |
| Any other error | This is probably a different problem. [Open an issue](https://github.com/3SENN/iphone-stuck-in-recovery-full-storage/issues/new?template=result.yml) and attach the log, with your ECID and serial number removed. |

## How it works

1. The phone reserves the whole system cryptex (about 5.6 GiB) in one go. APFS
   refuses a single reservation larger than about 84% of free space. On a nearly
   full phone the request is just over that limit, so the update fails. By then
   it has already deleted the old system, so the phone can't start.
2. Before reserving, the phone checks free space, using a cryptex size that the
   computer sends. The check passes, so the phone skips its low-space cleanup.
3. The patch makes idevicerestore send a larger size. The check now fails, the
   phone runs its cleanup, and the real reservation fits.

Details, measurements, and evidence: [docs/how-it-works.md](docs/how-it-works.md).

## Files

| Path | What it is |
|------|------------|
| [`patches/0001-…SystemOSSize.patch`](patches/0001-restore-Allow-overriding-the-declared-Cryptex1-SystemOSSize.patch) | The idevicerestore patch. Adds `IDEVICERESTORE_CRYPTEX_SIZE_MIB`. Without it set, idevicerestore behaves as upstream. |
| [`tools/suggest_cryptex_size.py`](tools/suggest_cryptex_size.py) | Picks the value to declare (step 5). |
| [`tools/apfs_prealloc_ceiling.py`](tools/apfs_prealloc_ceiling.py) | Reproduces the 84% APFS limit on a throwaway disk image. Optional. |
| [`docs/how-it-works.md`](docs/how-it-works.md) | Root cause, measurements, and what is proven. |

## License

- The patch is a change to idevicerestore and uses the same license,
  LGPL-2.1-or-later. See [`patches/LICENSE`](patches/LICENSE).
- Everything else is public domain under [CC0 1.0](LICENSE).
- There is no warranty. You use this at your own risk.

## About

I'm Senne. I worked this out while trying to save the photos on my own phone,
with help from Claude (Anthropic). The key insight, that the low-space cleanup
only runs when the space check fails, came from my disassembly of
`restored_update`.

Questions? Email me at [sennechin@gmail.com](mailto:sennechin@gmail.com). If you
tried the fix, please share your result through the
[result form](https://github.com/3SENN/iphone-stuck-in-recovery-full-storage/issues/new?template=result.yml)
so others can learn from it too.

The proper fix belongs in Apple's restore software. See
[section 8 of how-it-works](docs/how-it-works.md#8-the-real-fix-belongs-to-apple).
