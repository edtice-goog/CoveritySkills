/* A model for a function that does not exist: one letter is transposed.
 * cov-make-library builds it and cov-analyze runs with it, and neither says
 * anything; it changes nothing. */
void fail_hrad(const char *msg)
{
    __coverity_panic__();
}
