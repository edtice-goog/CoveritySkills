#include <stdlib.h>
#include <stdio.h>

/* Reads up to n ints from a file into a heap buffer and returns their sum.
 * Review comment claims the early-return path leaks 'buf'. */
int sum_from_file(const char *path, int n)
{
    int *buf = malloc(n * sizeof(int));
    FILE *f = fopen(path, "r");
    if (f == NULL)
    {
        return -1;
    }
    int count = 0;
    while (count < n && fscanf(f, "%d", &buf[count]) == 1)
    {
        count++;
    }
    int sum = 0;
    for (int i = 0; i < count; i++)
    {
        sum += buf[i];
    }
    fclose(f);
    free(buf);
    return sum;
}
