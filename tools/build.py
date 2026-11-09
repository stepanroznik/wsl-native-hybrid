#!/usr/bin/env python3
"""Build the early boot image and the driver archive from local Ubuntu packages."""

import argparse
import gzip
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid


REPO = Path(__file__).resolve().parents[1]
BOOT = REPO / 'boot'
EARLY_MODULES = (
    'nvme', 'vmd', 'ahci', 'virtio_pci', 'virtio_blk', 'xhci_pci', 'usbhid',
    'hid_generic', 'ntfs3', 'dm_crypt', 'dm_zero', 'vfat', 'nls_cp437',
    'nls_iso8859_1', 'loop', 'xts', 'aesni_intel',
)
APPLETS = ('sh', 'awk', 'blockdev', 'cat', 'chmod', 'cp', 'dd', 'dmesg', 'grep', 'head',
           'kill', 'ln', 'mkdir', 'mount', 'pivot_root', 'poweroff', 'readlink',
           'reboot', 'sha256sum', 'sleep', 'sort', 'switch_root', 'sync', 'tar', 'tr',
           'umount', 'uname')


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def output(*args, **kwargs):
    return run(*args, stdout=subprocess.PIPE, text=True, **kwargs).stdout


def put(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def executable(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f'{name} is required on the build host')
    return Path(path)


def pack_tool(source, target, root, library_path=None):
    env = os.environ.copy()
    env.pop('LD_LIBRARY_PATH', None)
    if library_path:
        env['LD_LIBRARY_PATH'] = library_path
    deps = output('ldd', source, env=env)
    if 'not found' in deps:
        raise RuntimeError(f'Missing shared library for {source.name}')
    put(source.resolve(), root / target)
    for path in set(re.findall(r'(/[^\s()]+)', deps)):
        dependency = Path(path)
        if not dependency.is_file():
            continue
        # Use the real ELF interpreter path; use the architecture library
        # directory for other dependencies, including an unpacked NBD client.
        name = dependency.name
        relative = (dependency.relative_to('/') if name.startswith('ld-linux')
                    else Path('lib/x86_64-linux-gnu') / name)
        destination = root / relative
        if destination.exists():
            if digest(destination) != digest(dependency):
                raise RuntimeError(f'Conflicting versions of shared library {name}')
        else:
            put(dependency.resolve(), destination)


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').digest()


def path_argument(value):
    # Keep Windows-relative paths unambiguous in GRUB, NTFS and the initramfs.
    p = PurePosixPath(value)
    if not value.startswith('/') or len(p.parts) < 2 or any(
        re.fullmatch(r'[A-Za-z0-9_.-]+', part) is None or part in ('.', '..') for part in p.parts[1:]
    ) or str(p) != value:
        raise argparse.ArgumentTypeError('Use an absolute NTFS-relative path with simple components, e.g. /HybridWSL/root/ubuntu.vhdx')
    return value


def pack_cpio(root, destination):
    with destination.open('wb') as file, gzip.GzipFile(fileobj=file, mode='wb', compresslevel=1, mtime=0) as archive:
        paths = b''.join(os.fsencode(str(p.relative_to(root))) + b'\0' for p in sorted(root.rglob('*')))
        with tempfile.TemporaryFile() as listing:
            listing.write(paths)
            listing.seek(0)
            with subprocess.Popen(['cpio', '--null', '-o', '-H', 'newc', '--owner=0:0', '--quiet'],
                                  cwd=root, stdin=listing, stdout=subprocess.PIPE) as packer:
                shutil.copyfileobj(packer.stdout, archive)
                if packer.wait():
                    raise RuntimeError('Could not create initramfs cpio archive')


def early_modules(root, release, modules, modules_root):
    target = root / 'lib/modules' / release
    target.mkdir(parents=True)
    for name in ('modules.order', 'modules.builtin', 'modules.builtin.modinfo'):
        if (modules / name).exists():
            put(modules / name, target / name)
    for module in EARLY_MODULES:
        for line in output('modprobe', '-d', modules_root, '-S', release, '--show-depends', module).splitlines():
            words = line.split()
            if words and words[0] == 'insmod':
                source = Path(words[1]).resolve()
                put(source, target / source.relative_to(modules.resolve()))
    run('depmod', '-b', root, release)


def build(args):
    modules = args.modules_root.resolve() / 'lib/modules' / args.release
    if not modules.is_dir():
        raise RuntimeError('Install the matching native Ubuntu kernel modules on the build host')
    if args.root_path == args.runtime_path:
        raise RuntimeError('The VHDX and driver archive require distinct paths')
    if args.output.exists():
        raise RuntimeError('Choose a new build output directory')
    if args.allow_unsigned_kernel:
        print('Unsigned kernel allowed for a disposable lab only.', flush=True)
    else:
        signatures = output('sbverify', '--list', args.kernel)
        if 'signature' not in signatures.lower() or 'no signature' in signatures.lower():
            raise RuntimeError('The kernel must have a PE signature')
    busybox = args.busybox or executable('busybox')
    applets = set(output(busybox, '--list').splitlines())
    if not set(APPLETS) <= applets:
        raise RuntimeError('The static BusyBox build lacks required applets: ' + ', '.join(sorted(set(APPLETS) - applets)))
    if 'statically linked' not in output('file', busybox.resolve()):
        raise RuntimeError('Use a statically linked BusyBox')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hybrid-build-') as temp:
        temp = Path(temp)
        outer, inner, runtime = (temp / name for name in ('outer', 'inner', 'runtime'))
        for root in (outer, inner):
            for name in ('bin', 'dev', 'sys', 'proc'):
                (root / name).mkdir(parents=True, exist_ok=True)
            put(busybox.resolve(), root / 'bin/busybox')
            for applet in APPLETS:
                (root / 'bin' / applet).symlink_to('busybox')
        for name in ('bootstrap',):
            (outer / name).mkdir()
        for name in ('host', 'run', 'esp', 'newroot', 'oldroot'):
            (inner / name).mkdir()
        put(BOOT / 'init', outer / 'init')
        for name in ('start', 'shutdown', 'storage.sh', 'hybrid-root-storage.service'):
            put(BOOT / name, inner / name)
        for path in (outer / 'init', inner / 'start', inner / 'shutdown'):
            path.chmod(0o755)
        for command in ('blkid', 'cryptsetup', 'dmsetup', 'modprobe', 'qemu-nbd', 'ntfs-3g.probe', 'timeout'):
            pack_tool(executable(command), 'usr/bin/' + command, inner)
        # The shutdown helper must stay in the initramfs after pivot_root.
        pack_tool(args.nbd_client or executable('nbd-client'), 'usr/bin/nbd-client', inner, args.nbd_library_path)
        libgcc = Path(output('cc', '-print-file-name=libgcc_s.so.1').strip()).resolve()
        put(libgcc, inner / 'lib/x86_64-linux-gnu/libgcc_s.so.1')
        for helper in ('keep-root-nbd', 'prepare-console'):
            run('cc', '-static', '-O2', '-Wall', '-Wextra', '-Werror', '-o', inner / helper, BOOT / (helper + '.c'))
        early_modules(inner, args.release, modules, args.modules_root.resolve())
        shutil.copytree(modules, runtime / 'lib/modules' / args.release, symlinks=True,
                        ignore=shutil.ignore_patterns('build', 'source'))
        members = ['lib/modules']
        if args.firmware:
            shutil.copytree(args.firmware, runtime / 'lib/firmware', symlinks=True)
            members.append('lib/firmware')
        # Build artifacts are per-machine and excluded from version control.
        args.output.mkdir()
        archive = args.output / 'drivers.tar.gz'
        compressor = 'pigz -1' if shutil.which('pigz') else 'gzip -1'
        run('tar', '-I', compressor, '-cf', archive, '-C', runtime, *members)
        values = dict(host_partuuid=str(args.host_partuuid), esp_partuuid=str(args.esp_partuuid),
                      root_path=args.root_path, runtime_path=args.runtime_path,
                      runtime_sha256=digest(archive).hex(), encryption=args.encryption,
                      desktop_uid=str(args.uid), desktop_gid=str(args.gid),
                      windows_access=args.windows_access)
        (inner / 'hybrid.conf').write_text(''.join(f'{k}={shlex.quote(v)}\n' for k, v in values.items()))
        run('tar', '-I', compressor, '-cf', outer / 'bootroot.tar.gz', '-C', inner, '.')
        pack_cpio(outer, args.output / 'initramfs.gz')
        shutil.copy2(args.kernel, args.output / 'vmlinuz')
        helper_root = temp / 'windows-next'
        helper_root.mkdir()
        run('cc', '-static', '-O2', '-Wall', '-Wextra', '-Werror', f'-DESP_GUID="{args.esp_partuuid}"',
            '-o', helper_root / 'init', BOOT / 'windows-next.c')
        pack_cpio(helper_root, args.output / 'windows-next.gz')
        make_menu(args.output)
        (args.output / 'esp-partuuid').write_text(str(args.esp_partuuid) + '\n')
        (args.output / 'host-partuuid').write_text(str(args.host_partuuid) + '\n')
        files = sorted(p for p in args.output.iterdir() if p.is_file())
        (args.output / 'SHA256SUMS').write_text(''.join(f'{digest(p).hex()}  {p.name}\n' for p in files))


def make_menu(directory):
    base = '/EFI/HybridWSL'
    options = 'console=tty0 rdinit=/init panic=10'
    masks = ('finalrd.service', 'hibernate.target', 'hybrid-sleep.target', 'suspend-then-hibernate.target',
             'docker.service', 'docker.socket', 'containerd.service', 'postgresql.service')
    native = ' '.join(f'systemd.mask={name}' for name in masks)
    (directory / 'grub.cfg').write_text(f'''search --no-floppy --file --set=root {base}/hybrid-wsl-v1.id
set timeout=8
set default=0
menuentry 'Shared Ubuntu (read-only storage check)' {{
    linux {base}/vmlinuz {options} hybrid.probe=1
    initrd {base}/initramfs.gz
}}
menuentry 'Shared Ubuntu (native desktop)' {{
    linux {base}/vmlinuz {options} {native} systemd.unit=graphical.target
    initrd {base}/initramfs.gz
}}
menuentry 'Windows Boot Manager (firmware restart)' {{
    linux {base}/vmlinuz {options}
    initrd {base}/windows-next.gz
}}
''')
    (directory / 'hybrid-wsl-v1.id').write_text('hybrid-wsl-v1\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release', required=True, help='Native Ubuntu kernel release matching /lib/modules')
    p.add_argument('--kernel', required=True, type=Path)
    p.add_argument('--modules-root', type=Path, default=Path('/'), help='Root containing lib/modules for the selected kernel')
    p.add_argument('--host-partuuid', required=True, type=uuid.UUID)
    p.add_argument('--esp-partuuid', required=True, type=uuid.UUID)
    p.add_argument('--root-path', type=path_argument, default='/HybridWSL/root/ubuntu.vhdx')
    p.add_argument('--runtime-path', type=path_argument, default='/HybridWSL/boot/drivers.tar.gz')
    p.add_argument('--encryption', choices=('bitlocker', 'vault', 'none'), default='bitlocker')
    p.add_argument('--uid', type=int, default=1000)
    p.add_argument('--gid', type=int, default=1000)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--busybox', type=Path, help='Optional path to a trusted static BusyBox')
    p.add_argument('--nbd-client', type=Path, help='Optional path to a trusted Ubuntu nbd-client binary')
    p.add_argument('--nbd-library-path', help='Library search path for an unpacked nbd-client package')
    p.add_argument('--firmware', type=Path, help='Optional prepared firmware directory to include')
    p.add_argument('--windows-access', choices=('none', 'read-only', 'read-write'), default='none',
                   help='Optional native /mnt/c view. The backing file directories are read-only.')
    p.add_argument('--allow-unsigned-kernel', action='store_true', help='Disposable VM testing only')
    args = p.parse_args()
    if not re.fullmatch(r'[0-9][0-9A-Za-z.+-]*-generic', args.release) or min(args.uid, args.gid) < 1:
        p.error('Use a native Ubuntu -generic kernel and a non-root desktop UID/GID')
    if args.host_partuuid == args.esp_partuuid:
        p.error('The host partition and ESP must have distinct identities')
    if args.windows_access == 'read-write' and (len(PurePosixPath(args.root_path).parts) < 3 or
                                               len(PurePosixPath(args.runtime_path).parts) < 3):
        p.error('For write access, both backing files must be in subdirectories of the NTFS root')
    build(args)
    print(f'Build ready at {args.output}. Begin with the read-only entry.')


if __name__ == '__main__':
    main()
