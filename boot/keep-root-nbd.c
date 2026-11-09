#include <stdio.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    if (argc < 2)
        return 2;

    /* systemd preserves root storage daemons whose argv[0] starts with @. */
    argv[0] = "@qemu-nbd";
    execv("/usr/bin/qemu-nbd", argv);
    perror("exec qemu-nbd");
    return 1;
}
