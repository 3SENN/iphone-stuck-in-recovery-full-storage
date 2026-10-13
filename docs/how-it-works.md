# How it works

Why the update fails, and why declaring a larger cryptex size fixes it.

All numbers come from my own iPhone 15 Pro (`iPhone16,1`, `d83ap`). Its
iOS 26.5 → 27.0 update failed, and I recovered it on iOS 27.0.1 (24A446) on
2026-09-29.

- [1. The failure](#1-the-failure)
- [2. Why APFS refuses: the 84% limit](#2-why-apfs-refuses-the-84-limit)
- [3. Why the update starts anyway: the space check](#3-why-the-update-starts-anyway-the-space-check)
- [4. Why declaring a larger size fixes it](#4-why-declaring-a-larger-size-fixes-it)
- [5. The successful run](#5-the-successful-run)
- [6. What is proven and what is inferred](#6-what-is-proven-and-what-is-inferred)
- [7. Open questions](#7-open-questions)
- [8. The real fix belongs to Apple](#8-the-real-fix-belongs-to-apple)

## 1. The failure

During a data-preserving update, the restore software on the phone (`restored`)
installs the system cryptex, a 6,031,409,152-byte (5,752 MiB) disk image. It fails
here:

```
Transfer: Receiving 2348810240 bytes, writing 6031409152 bytes
Transfer: Failed preallocation of 6031409152 bytes for /mnt9/cryptex1/current/os.dmg: Unknown error: -1.
Transfer: Failed preallocation due to space. No hope in this succeeding, bailing.
CHECKPOINT FAILURE:(FAILURE:100) install_splat [0]D(failed to install splat)
```

`restored` asks APFS to reserve the whole image in a single
`fcntl(F_PREALLOCATE, F_ALLOCATEALL)` call, and APFS refuses.

By this point the update has already deleted the old system volume and written the
new one. When the cryptex fails, the phone has no working system left and can only
start in Recovery mode. Every retry fails at the same step.

## 2. Why APFS refuses: the 84% limit

APFS does not grant a single all-at-once reservation larger than about **84% of the
free space**, even when the space is free. The limit is a fraction of free space,
not a fixed amount:

| Free space | Largest single request granted | Limit |
|-----------:|-------------------------------:|------:|
| 7,967 MiB  | 6,724 MiB                      | 84.40% |
| 6,945 MiB  | 5,858 MiB                      | 84.35% |
| 3,880 MiB  | 3,261 MiB                      | 84.03% |
| 3,534 MiB  | 2,967 MiB                      | 83.96% |

I measured these on macOS 26 with
[`tools/apfs_prealloc_ceiling.py`](../tools/apfs_prealloc_ceiling.py). It runs on
a throwaway disk image, so you can safely try it yourself:

```sh
python3 tools/apfs_prealloc_ceiling.py --size-gib 8
```

On my phone, at the cryptex step:

| | |
|---|---:|
| Free space | 6,955,032,576 bytes (6,633 MiB) |
| Cryptex reservation | 6,031,409,152 bytes (5,752 MiB) |
| Reservation as share of free space | **86.7%**, above the ~84% limit |
| Free space needed to stay under 84.35% | 6,819 MiB |
| Shortfall | **about 186 MiB** |

## 3. Why the update starts anyway: the space check

Before it installs the cryptex, `restored` checks whether there is enough space:

```
ramrod_splat_get_total_cryptex_size: Size of Cryptex1,SystemOS is 5752 MB
SpaceNeededForRestore: 6040 MB ContainerFreeSpace: 6634 MB  Sufficient space available for upgrade install
```

The check adds up the sizes it expects to write and compares the total with free
space. It does not account for the 84% limit, so it approves the update with
594 MB to spare.

`restored` also has a **low-space cleanup** that frees purgeable data. It runs
only when this check reports too little space. Here the check passes, so the
cleanup is skipped, even though a few hundred MB of cleanup would have been enough.

## 4. Why declaring a larger size fixes it

The space check and the reservation get the cryptex size from different places:

| Step | Where the size comes from | Can the computer change it? |
|------|---------------------------|:---------------------------:|
| Space check (`SpaceNeededForRestore`) | `Info/Cryptex1,SystemOSSize` in the build identity sent by the computer | Yes |
| Reservation (`F_PREALLOCATE`) | The cryptex image itself | No |

Evidence: when I declared 4,096 MiB instead of the real 5,752 MiB,
`SpaceNeededForRestore` dropped by exactly the difference (6040 → 4384 MB), while
the reservation still asked for 6,031,409,152 bytes.

The patch adds `IDEVICERESTORE_CRYPTEX_SIZE_MIB`, which makes idevicerestore
declare a **larger** size. That leads to this sequence:

1. `SpaceNeededForRestore` rises above `ContainerFreeSpace`.
2. `restored` treats the phone as low on space and runs its cleanup.
3. The cleanup frees enough space for the real 5,752 MiB reservation to fall under
   the 84% limit.
4. The cryptex installs and the update completes.

On my phone, declaring 6,500 MiB raised `SpaceNeededForRestore` to about
6,788 MB (6040 + 748), 154 MB more than the 6,634 MB free.
[`tools/suggest_cryptex_size.py`](../tools/suggest_cryptex_size.py) uses the same
calculation: it picks a value that puts the space check about 150 MB over free space.

## 5. The successful run

From the `restore_*.log` that idevicerestore saved during the run with
`IDEVICERESTORE_CRYPTEX_SIZE_MIB=6500` (local times, trimmed):

```
22:47:29 Checkpoint started   id: 0x6A6 (install_splat)
22:47:29 Declaring Cryptex1,SystemOSSize as 6500 MiB (real size 5752 MiB) ...
22:47:31 Sending Cryptex1,SystemOS now (2348810240 bytes)
22:48:10 Done sending Cryptex1,SystemOS
22:48:10 Checkpoint completed id: 0x6A6 (install_splat) result=0
22:48:49 Sealing System Volume (77)
22:49:22 Status: Restore Finished
```

Afterwards my phone started normally:

```
ProductVersion : 27.0.1
BuildVersion   : 24A446
DeviceName     : <unchanged>
idevicepair validate -> SUCCESS
```

The phone went to the lock screen, not the Setup screen. Its name and the pairing
record from before the failure were still valid. Both are stored on the Data
volume, so the Data volume survived. I then checked the phone itself: it was on
the new iOS version, and all my photos, apps and data were still there.

## 6. What is proven and what is inferred

**Proven**

- The declared size feeds the space check one-for-one (see section 4).
- My attempts with the real size failed at the cryptex step. The run with
  6,500 MiB declared succeeded.
- After that run, my phone booted on iOS 27.0.1 with all its data, photos and
  apps included.

**Inferred**

- That the low-space cleanup is what freed the space. idevicerestore's
  `restore_*.log` from the successful run contains the phone's log from the
  *previous* attempt, not from this one. So the cleanup lines for the successful run
  were never captured. The cleanup is the explanation that fits all my
  measurements.
- What the cleanup removes. My disassembly of `restored_update` shows an APFS purge,
  an offline purge of caches, photos, mail and logs, and staged app deletion.
  Exactly which photo and mail data it removes is not known. Most likely it is only
  data that iOS has marked as purgeable.

## 7. Open questions

- The smallest over-declaration that works, and whether ~150 MB past free space is
  right for other devices.
- Whether the fix works on other models (iPad, A15/A16 iPhones) and other iOS
  versions.
- The exact APFS rule behind the 84% limit.

If you try the fix, please
[report your result](https://github.com/3SENN/iphone-stuck-in-recovery-full-storage/issues/new?template=result.yml),
including the numbers from your log.

## 8. The real fix belongs to Apple

This patch works around a bug in Apple's restore software. Any one of these
changes in `restored` would prevent it:

- Reserve the cryptex in chunks, or fall back to a normal write when the one-shot
  `F_ALLOCATEALL` reservation fails.
- Include the 84% limit in the space check.
- Run the low-space cleanup before deleting the old system volume.
