# Source checkout lock

Shallow clones are kept under `references/`. Record a refreshed commit here
if a checkout is advanced. `--depth 1` clones use their resolved commit, not a
floating branch name, for local review.

| Local path | Source | Commit | Why retained |
|---|---|---|---|
| `references/ubuntu-gts9-ultra` | [agcarbajo/ubuntu-galaxy-tab-s9-ultra](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra) | `ab3240123ce64f9be08f5e225cd27f53835d0589` | Latest mainline Ubuntu X910 port; rootfs, boot bundle, hardware status, GNOME 50 and update architecture |
| `references/ubuntu-gts9-ultra/external/galaxy-companion` | [agcarbajo/galaxy-companion](https://github.com/agcarbajo/galaxy-companion) | `cbf80fd6b163e03a7b2fd998b0a2cd4d7f099ee5` | Device companion app profile/update design; submodule of the Ubuntu reference |
| `references/pmos-gts9-ultra` | [agcarbajo/postmarketos-galaxy-tab-s9-ultra](https://github.com/agcarbajo/postmarketos-galaxy-tab-s9-ultra) | `b1dcca03fdc7952de60c3e9ab49e860b6bd45e8c` | Upstream-first device support, pmaports and hardware validation notes |
| `references/ubuntu-touch-gts9-ultra` | [agcarbajo/ubuntu-touch-galaxy-tab-s9-ultra](https://github.com/agcarbajo/ubuntu-touch-galaxy-tab-s9-ultra) | `97821e864b6fd2555d217870b7a44f38470907f9` | S9-family Android/Halium boot and device-delta reference; not the mainline kernel path |
| `references/original-gts9wifi-fedora` | [nacht20-de/gts9wifi-fedora-linux](https://github.com/nacht20-de/gts9wifi-fedora-linux) | `ab123e7d1dbc0cbcd35661f9761197e977b15aa9` | Original X710 Fedora/mainline port and shared-family bring-up notes |
| `references/ztos-arch-s9-phone` | [Zerone-Laboratories/ztOS](https://github.com/Zerone-Laboratories/ztOS) | `b3bff4734727cea7e6d9c5092abdce415516daf2` | Beta native Arch ARM project for the *Galaxy S9 phone* (Exynos 9810); README says installer is not hardware-tested; image/build separation only, not Tab S9 support |
| `references/arch-arm-synport` | [VitaminDB/synport](https://github.com/VitaminDB/synport) | `f7dd3bc06ab500f436016711f344f2df0d20b4de` | Arch ARM phone/tablet install and rollback UX; repo is binary/release-focused and its Tab A is a different device; no X810 code is reused |

The X710 Ubuntu Touch GitLab URL discovered in the forum was not cloneable
without credentials from this host; no empty checkout is retained. Whitehat
Hardware's X810 bring-up is documented on its site, but a public source
checkout was not found. Neither is presented here as a reproducible source
tree.

## Refresh checkouts

From the workspace root (`linux-port/`):

```sh
git -C references/ubuntu-gts9-ultra fetch --depth=1 origin
git -C references/pmos-gts9-ultra fetch --depth=1 origin
git -C references/ubuntu-touch-gts9-ultra fetch --depth=1 origin
git -C references/original-gts9wifi-fedora fetch --depth=1 origin
git -C references/ztos-arch-s9-phone fetch --depth=1 origin
git -C references/arch-arm-synport fetch --depth=1 origin
```

Do not reset/advance these checkouts without updating the commit table and
re-reading the relevant docs.
