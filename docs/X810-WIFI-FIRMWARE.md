# X810 Wi-Fi firmware staging and provenance

`tools/stage-x810-wifi-firmware.sh <rootfs-dir>` stages a narrowly scoped
WCN6855 set into a disposable rootfs below the ignored `work/`
or `tmp/` directories. It installs or
replaces only:

- `usr/lib/firmware/ath11k/WCN6855/hw2.1/amss.bin`
- `usr/lib/firmware/ath11k/WCN6855/hw2.1/m3.bin`
- `usr/lib/firmware/ath11k/WCN6855/hw2.1/board-2.bin` (only when its exact
  X810 board slot needs the tuned payload, or the rootfs has only `.xz`)

It does not alter the source firmware repositories, stage `regdb.bin`, or stage
the proprietary VPU or Cirrus speaker-protection firmware. It refuses to write
outside this project tree, rejects symlinked firmware paths, and validates all
downloads and board-data before writing to the rootfs.

## Pins

The source URLs and hashes below match
`x810-fedroid/rootfs/stage-public-firmware.sh` at x810-fedroid commit
`691763578b51f859f51568a6efa3946a7b366eb7` (2026-11-04). The local
`x810-fedroid/tools/bdftool.py` is pinned by SHA-256
`c2f851d7d9700fca7df41df19d291122877c6008e22722250f68fddbe72e4cc7`.
The source staging script at that revision has SHA-256
`41f8ae6b2046534f8c33bb5a70acc1c49dd3bfa9a26986c2f80af937d096dc07`.

| Item | Public source | SHA-256 |
|---|---|---|
| WCN6855 IOE `amss.bin` | `CodeLinaro-mirror/ath-firmware_ath11k-firmware/main/WCN6855/hw2.0@nfa765/1.1/WLAN.HSP.1.1-04866.5-QCAHSPSWPL_V1_V2_SILICONZ_IOE-1/amss.bin` | `8cb5e63877c7cfdc5002a7d28bc5d7f7d20368183e6f93b12c977bfd0351c7b7` |
| WCN6855 IOE `m3.bin` | same directory, `m3.bin` | `d20460e104b85a7be9cdb5199c4d8b94a9787912e3f920acd845694d4d71f730` |
| Tuned board-data payload | `CodeLinaro-mirror/ath-firmware_ath11k-firmware/main/WCN6855/hw2.0/board-2.bin`, entry `...,variant=NTM_TW220` | `77b1b9ef636ce8492723aa7c2ff2c42c2e5e81a43967d7f32bfdef93a31bf8c4` |
| Optional reference BDF container | same `hw2.0/board-2.bin` | `9287fa8d14d915892666b03e9403135875d08371fd1438d2c6d9fe96ae71cf68` |

The default Arch Linux ARM bootstrap archive is separately pinned by
[`ALARM-ROOTFS.lock`](ALARM-ROOTFS.lock). In that archive, the generic payload
in the exact X810 slot has MD5
`0e92fa42e6b9895e4afd7a281bbed079` and SHA-256
`9c5266d14cbe3eb40a4137e2fbe6199e10f14b1b8100a401b6de153326124a5e`.
The target slot is
`bus=pci,vendor=17cb,device=1103,subsystem-vendor=17cb,subsystem-device=0108,qmi-chip-id=18,qmi-board-id=255`.
Only that exact name is changed to the pinned tuned payload. The script fails
closed if the slot is absent, duplicated, or neither the pinned generic nor
pinned tuned payload.

The `bdftool.py` `swap` CLI treats a base name as matching every
`,variant=` entry with that base. This staging tool therefore uses the pinned
tool to parse, list, extract, and verify the API-v2 container, then performs a
raw TLV-preserving patch of only the exact board-name entry. Unrelated top-level
entries are copied verbatim; `bdftool.py` also verifies that every other entry's
name, size, and payload MD5 are unchanged. This preserves the NTM_TW220 variant
and unrelated board entries.

## Provenance and redistribution assumptions

The firmware bytes are fetched from the public CodeLinaro mirror of Qualcomm's
ath11k-firmware tree. The fixed hashes establish content integrity; a public
mirror and successful hash check are **not** a license grant or proof of
redistribution rights. This workflow assumes local staging for the owner's
device only. Do not commit firmware blobs, publish a rootfs/image containing
them, or redistribute them unless the applicable upstream firmware terms and
permissions have been reviewed. The tuned BDF is sourced from the public
`NTM_TW220` variant and substituted only into the X810's measured PCI/QMI ABI
slot; it is not represented as Samsung-, Qualcomm-, or Lenovo-endorsed X810
firmware.

This is a local preparation script, not an on-device installer. It must be run
against a project-local staging rootfs, never Windstation's live filesystem.
