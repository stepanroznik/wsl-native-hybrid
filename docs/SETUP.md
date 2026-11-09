# Setup and recovery

This is a hands-on, experimental procedure for experienced Linux and Windows users. The exact laptop-specific prototype used different paths, additional D/E mounts, and a custom recovery-key vault. Do not run these commands on a machine without a verified independent backup and recovery media.

## 1. Prepare Windows and a separate clone

Record the existing WSL distro name, Windows Boot Manager entry, disk layout, and BitLocker recovery key ID. Verify the full recovery key is accessible from another device. Save and stop databases, Docker, VS Code, and other workloads in the source distro. From PowerShell, stop **only** that distro and export a clone:

```powershell
wsl --list --verbose
wsl --terminate YOUR_SOURCE_DISTRO
.\windows\New-HybridClone.ps1 -SourceDistro YOUR_SOURCE_DISTRO
```

The script refuses a running source and an existing destination. It uses the supported WSL VHD export and leaves the original registered. It checks fixed NTFS destination space using the source VHD's logical file size and a reserve. A stopped distro can be started by another program during the export, so keep WSL clients closed until the script finishes. Export time and disk usage depend on the source.

Inspect the clone, then register it as a separate WSL distro:

```powershell
wsl --import-in-place HybridUbuntu C:\HybridWSL\root\ubuntu.vhdx
wsl --distribution HybridUbuntu --user root
```

Verify the clone's user, files and services. Install a desktop and NetworkManager inside the clone if desired. Ensure `/sbin/init` is systemd and that there is space for the native kernel's modules and firmware. Keep the original source distro until the clone and restore process are verified. Treat the clone and source as independent after the copy.

## 2. Prepare a trusted Linux build environment

Use a separate trusted Ubuntu environment with the **same architecture** as the target. It needs the signed target Ubuntu `-generic` kernel image and its corresponding `/lib/modules/<release>` tree. Do not substitute the Microsoft WSL kernel. An Ubuntu live environment can be used if it has sufficient memory and writable build space.

Install the distribution packages that supply these commands: `busybox-static`, `qemu-utils`, `nbd-client`, `cryptsetup`, `kmod`, `ntfs-3g`, `util-linux`, `sbsigntool`, `cpio`, `gcc`, a static C library, Python 3.11+, and the signed Ubuntu shim/GRUB packages. Install target hardware firmware from trustworthy Ubuntu packages. The builder uses locally installed tools and does not download packages.

Identify the Windows NTFS partition and EFI System Partition with `lsblk -f` and `sudo blkid`. Use their GPT **PARTUUIDs**, not filesystem UUIDs, labels, or the example below. Identify the native desktop UID and GID from the clone. The signed kernel must match the chosen modules release exactly.

```sh
python3 tools/build.py \
  --release YOUR_UBUNTU_RELEASE-generic \
  --kernel /path/to/signed/vmlinuz \
  --host-partuuid YOUR-WINDOWS-PARTUUID \
  --esp-partuuid YOUR-EFI-PARTUUID \
  --encryption bitlocker \
  --uid 1000 --gid 1000 \
  --windows-access read-only \
  --output /tmp/hybrid-build
```

For an unencrypted host volume, use `--encryption none`. For a pre-existing LUKS recovery-key vault in the original prototype format, use `--encryption vault` only after reading [SECURITY.md](SECURITY.md). The builder checks for a PE signature with `sbverify`, but this check does not establish that your firmware trusts that signature or that it has not been revoked. `--allow-unsigned-kernel` is only for isolated VM tests.

The default paths are `/HybridWSL/root/ubuntu.vhdx` and `/HybridWSL/boot/drivers.tar.gz`, relative to the NTFS volume. Paths contain simple ASCII components to make early boot unambiguous. To choose others, pass `--root-path` and `--runtime-path`. The runtime archive is built from **all** installed modules for the selected release. Pass `--firmware /path/to/prepared/firmware` to include a prepared firmware tree. The archive must fit in the initramfs RAM filesystem when expanded.

`--windows-access read-only` exposes the Windows volume at `/mnt/c` in native Linux. `read-write` allows writes but overlays the VHDX and driver archive's parent directories with read-only bind mounts. It is not a backup and does not protect against privileged Linux processes. The default is `none`. Other Windows drives are not mounted by this generic build.

Copy `drivers.tar.gz` from the build to the configured path on the Windows volume. Copy `vmlinuz`, `initramfs.gz`, and the remaining EFI build outputs together; do not mix files from different builds. Keep the build output private because it contains machine-specific GPT identifiers.

## 3. Install the EFI files

From the trusted Linux environment, mount the intended EFI System Partition read-write at a **dedicated mountpoint** such as `/mnt/esp`. It must contain `EFI/Microsoft/Boot/bootmgfw.efi`. Check the detected partition and mountpoint a second time. Back up the ESP and firmware boot order. Then:

```sh
sudo tools/install-efi.sh /tmp/hybrid-build /mnt/esp
```

The script checks the selected partition PARTUUID, checks build hashes and space, and refuses to overwrite an existing `EFI/ubuntu` or `EFI/HybridWSL` directory. The shim and GRUB are taken from the build host's signed Ubuntu packages. The script does not create firmware entries.

Use `sudo efibootmgr -v` to record existing entries. Create a **non-default test entry** pointing at `\EFI\ubuntu\shimx64.efi` on the selected EFI disk and partition, using your firmware's supported `efibootmgr --create-only` syntax. Check `efibootmgr --help` for your installed version. Select it using your firmware's one-time boot menu. Do not change the permanent boot order until both Linux and the direct Windows firmware entry have been tested. Do not use a GRUB chainload entry for Windows without understanding the BitLocker consequences.

## 4. Test and run

1. Fully shut down Windows. Select the new Linux test entry through the firmware one-time boot menu.
2. Select **Shared Ubuntu (read-only storage check)**. Enter the BitLocker recovery password locally if requested. The probe checks the backing VHDX and mounts its ext4 root with `ro,noload`. Expect `HYBRID_READ_ONLY_PASSED`, then power off.
3. Boot Windows using the firmware's direct Windows Boot Manager entry and verify its normal login and BitLocker state.
4. Repeat the one-time Linux boot and select **Shared Ubuntu (native desktop)**. Test login, networking, sound, displays, USB, sleep policy, and shutdown. The Windows volume is checked before read-write mount. A failing readiness check must be investigated from Windows; do not force-mount a dirty or hibernated NTFS volume.
5. Boot Windows directly and start `HybridUbuntu` in WSL. Verify changes made natively are present. Shutdown WSL cleanly before the next native boot.
6. Only after those checks, try the menu's one-shot firmware return to Windows. Keep the Windows recovery key accessible. Check that Windows boots without repeated recovery prompts.

The first native boot can update files in the shared clone. Some WSL configuration and services may need environment-specific treatment. The included DNS bind handles only the common `/mnt/wsl/resolv.conf` symlink and expects systemd-resolved in native Linux. Test network and resolver behavior explicitly.

## Recovery and removal

Choose Windows Boot Manager directly from the firmware boot menu if Linux fails. Do not unregister the shared WSL distro as a troubleshooting step. `wsl --unregister` permanently removes a distro and may remove its storage. Restore a verified independent backup if the filesystem or host volume is damaged.

To remove the hybrid boot integration, first boot Windows directly and verify it works. From trusted Linux, remove the firmware test entry with `efibootmgr`, after checking its exact ID and current boot order. Remove the files this installation created only after verifying they are not used by another OS. The installer refuses pre-existing directories to make ownership identifiable. Do not touch `EFI/Microsoft`. Keep the VHDX if it is still registered in WSL.

## Updates and storage

The generated `SHA256SUMS` includes machine-specific identifiers, so keep build directories, vaults, logs, EFI backups, and disk images out of public repositories. After a kernel, firmware, shim or GRUB update, rebuild with matching modules and re-run disposable and read-only checks before changing the installed payload. Keep a tested previous boot path or recovery USB available.
