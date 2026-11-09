#!/bin/bash
# Install only the Linux payload onto a verified, already-mounted ESP.
set -euo pipefail
if [[ $# != 2 || $EUID != 0 ]]; then
    echo 'Usage: sudo tools/install-efi.sh BUILD_DIR ESP_MOUNTPOINT' >&2
    exit 2
fi
build=$(realpath -- "$1")
esp=$(realpath -- "$2")
[[ $(findmnt -n -o FSTYPE --mountpoint "$esp") == vfat ]] || { echo 'Expected a mounted FAT EFI partition' >&2; exit 1; }
device=$(findmnt -n -o SOURCE --mountpoint "$esp")
[[ $(blkid -s PARTUUID -o value "$device") == "$(cat "$build/esp-partuuid")" ]] || { echo 'EFI partition identity differs' >&2; exit 1; }
[[ -f "$esp/EFI/Microsoft/Boot/bootmgfw.efi" ]] || { echo 'Windows Boot Manager is missing from this ESP' >&2; exit 1; }
[[ ! -e "$esp/EFI/ubuntu" && ! -e "$esp/EFI/HybridWSL" ]] || { echo 'The destination already has an Ubuntu or hybrid bootloader. Inspect it manually.' >&2; exit 1; }
(cd "$build" && sha256sum -c SHA256SUMS)
shim=/usr/lib/shim/shimx64.efi.signed.latest
grub=/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed
[[ -s $shim && -s $grub ]] || { echo 'Install the trusted Ubuntu signed shim and GRUB packages' >&2; exit 1; }
files=(vmlinuz initramfs.gz windows-next.gz hybrid-wsl-v1.id)
required=$((32 * 1024 * 1024))
for f in "${files[@]}" grub.cfg; do required=$((required + $(stat -c %s "$build/$f"))); done
required=$((required + $(stat -Lc %s "$shim") + $(stat -Lc %s "$grub")))
free=$(df -B1 --output=avail "$esp" | tail -n 1)
((free >= required)) || { echo 'EFI space is insufficient with a 32 MiB reserve' >&2; exit 1; }
# The Ubuntu signed GRUB uses the Ubuntu EFI directory. Existing installations
# are refused above. No existing boot entry or Windows file is modified.
mkdir "$esp/EFI/HybridWSL"
trap 'rm -f -- "$esp/EFI/HybridWSL/"{vmlinuz,initramfs.gz,windows-next.gz,hybrid-wsl-v1.id}; rmdir "$esp/EFI/HybridWSL" 2>/dev/null || true' ERR
for f in "${files[@]}"; do cp -- "$build/$f" "$esp/EFI/HybridWSL/$f"; cmp -- "$build/$f" "$esp/EFI/HybridWSL/$f"; done
mkdir "$esp/EFI/ubuntu"
trap 'rm -f -- "$esp/EFI/ubuntu/"{shimx64.efi,grubx64.efi,grub.cfg} "$esp/EFI/HybridWSL/"{vmlinuz,initramfs.gz,windows-next.gz,hybrid-wsl-v1.id}; rmdir "$esp/EFI/ubuntu" "$esp/EFI/HybridWSL" 2>/dev/null || true' ERR
cp -- "$shim" "$esp/EFI/ubuntu/shimx64.efi"
cp -- "$grub" "$esp/EFI/ubuntu/grubx64.efi"
cp -- "$build/grub.cfg" "$esp/EFI/ubuntu/grub.cfg"
cmp -- "$shim" "$esp/EFI/ubuntu/shimx64.efi"
cmp -- "$grub" "$esp/EFI/ubuntu/grubx64.efi"
cmp -- "$build/grub.cfg" "$esp/EFI/ubuntu/grub.cfg"
sync -f "$esp"
trap - ERR
printf 'EFI files installed. Register a test boot entry with efibootmgr --create-only.\n'
