# Testing and validation

## Evidence and scope

The original machine-specific prototype was tested with disposable VHDX/BitLocker fixtures in a Secure Boot VM, then on one physical laptop. It demonstrated read-only access to the cloned root, persistent native Linux, WSL access to that same root, display and Wi-Fi operation, and a one-shot firmware path back to Windows. The original laptop also exposed real limitations: Secure Boot trust differed from the VM, one USB adapter needed additional drivers, network and desktop configuration needed native-specific handling, BitLocker recovery occurred during a GRUB Windows chainload, and shutdown initially failed after a mapping had already been closed.

The generalized scripts in this repository have different configuration and packaging. A pass in the original prototype is not evidence that every generalized feature has been tested. The reconstructed builder and its read-only boot entry passed a disposable QEMU test with a synthetic GPT disk, NTFS volume and ext4 VHDX. The test confirmed read-only attachment and clean shutdown. The reconstructed writable desktop, BitLocker unlock, Secure Boot chain, and firmware Windows handoff have not yet been tested end to end. Do not test a new build first on your only installation.

The original prototype later booted and restarted successfully using buffered VHDX access with write flushing and bounded device-mapper cleanup without udev synchronization. The corresponding changes in this generalized repository need a fresh end-to-end test.

## Static checks

```sh
python3 -m py_compile tools/build.py
for script in boot/init boot/start boot/shutdown boot/storage.sh; do sh -n "$script"; done
bash -n tools/install-efi.sh
cc -static -O2 -Wall -Wextra -Werror -o /tmp/keep-root-test boot/keep-root-nbd.c
cc -static -O2 -Wall -Wextra -Werror -o /tmp/prepare-console-test boot/prepare-console.c
cc -static -O2 -Wall -Wextra -Werror -DESP_GUID='"00000000-0000-4000-8000-000000000001"' -o /tmp/windows-next-test boot/windows-next.c
```

Use synthetic identifiers and disposable data for testing. Do not pass real keys, vaults, or images into CI. The `--allow-unsigned-kernel` build option is for an isolated VM only.

## Required end-to-end checks

Create disposable GPT/NTFS/BitLocker fixture disks and a disposable ext4 VHDX. Exercise read-only and writable native boot, Windows-volume cleanliness rejection, NBD lifetime across systemd shutdown, already-inactive data mappings, and return to WSL. Test Secure Boot and firmware handoff with disposable OVMF variable stores. Verify the test kernel and modules match.

Then test the hardware read-only entry and the firmware Windows return on the actual machine. A VM cannot establish physical firmware certificate trust, TPM measurements, actual BitLocker recovery behavior, hardware support, or power-off behavior. Record those separately.
