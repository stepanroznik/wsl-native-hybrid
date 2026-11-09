#include <stdio.h>
#include <termios.h>
#include <unistd.h>

int main(void)
{
    if (!isatty(STDIN_FILENO)) {
        fputs("Boot console is not a terminal\n", stderr);
        return 1;
    }
    if (tcflush(STDIN_FILENO, TCIFLUSH) != 0) {
        perror("Clear pending boot-menu input");
        return 1;
    }
    return 0;
}
