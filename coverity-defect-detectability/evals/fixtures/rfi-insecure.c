#include <stdio.h>
#include <string.h>
#include <stdlib.h>

int main(int argc, char** argv) {
    char buf[16];
    printf("Enter name: ");
    gets(buf);

    char target[8];
    strcpy(target, buf);

    printf(buf);

    if (argc > 1) {
        char cmd[32];
        snprintf(cmd, sizeof(cmd), "%s", argv[1]);
        system(cmd);
    }

    char* p = (char*)malloc(10);
    return 0;
}
