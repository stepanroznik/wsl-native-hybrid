# Security and privacy

The Windows BitLocker recovery password unlocks the encrypted Windows volume. Treat it like a high-value credential. Never put recovery passwords, decrypted VPN keys, vaults, WSL VHDX files, browser profiles, logs, screenshots, real GPT IDs, or configuration generated for a particular machine into a public repository.

`--encryption bitlocker` asks cryptsetup for the recovery password on the local console at each Linux boot. It does not write that password to an initramfs file. Enter it only on a trusted machine whose boot artifacts you have verified.

`--encryption vault` supports the format used by the original laptop prototype. A LUKS2 encrypted file at `EFI/HybridWSL/windows-unlock.luks` contains the 55-byte ASCII Windows recovery password in its first decrypted bytes. The initramfs opens it read-only and pipes those bytes to cryptsetup. This repository deliberately does not create or provision a vault automatically. Creating one requires a trusted separate Linux environment, independent recovery-key backups, and validation that the record matches the intended Windows volume.

A six-character or PIN-like password is vulnerable to offline guessing. A delay enforced by boot scripts does not constrain an attacker who copies a LUKS file. A recovery key inside the vault grants access to the Windows volume if the vault password is recovered. TPM sealing is not implemented.

Secure Boot authenticates certain EFI components and the signed kernel when configured correctly. A separate initramfs, GRUB configuration, and driver archive are not necessarily authenticated. An attacker able to replace them can modify the code that asks for your recovery password. The archive's SHA-256 value is stored alongside boot code and does not authenticate against a malicious replacement. For stronger assurance, design and test an authenticated UKI or another verified boot chain supported by your hardware and signing policy.

The Windows menu entry writes a one-shot UEFI `BootNext` variable. It refuses ambiguous matching entries and a conflicting existing one-shot boot target. Firmware and BitLocker policies differ. Keep the recovery key available and test the firmware path before setting the menu as the default.
