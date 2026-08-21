/* Setup Klocwork analysis with:
 *
 * Klocwork version is 2022.2
 *
 * kwcheck create
 * kwinject -o build.out \path\to\gcc.exe main.c -o main.exe
 * kwcheck import build.out
 *
 * Open project in Klocwork desktop
 * Enable all C checkers.
 * Run analysis.
 *
 * Expected result: An issue should be reported for reading the uninitialized
 * variable 'value' in main.c at line 41.
 *
 * Actual result: No such issue is reported.
 */

/** Might set *value to 42.
 *
 *  Not every path through fill_int set *value, instead leaving it unchanged.
 *
 *  This is a simplified version.  In the real software, value might or might
 *  not be updated depending on configuration values loaded at run-time.
 */
static void fill_int(int* value)
{
    static int b = 0;
    if (b == 1)
    {
        *value = 1;
    }
}

int main(void)
{
    int value;

    fill_int(&value);
    /* I'd like to see a checker fail here since value is possibly not initialized. */
    if (value == 1)
    {
        return 0;
    }
    else
    {
        return 1;
    }
}
