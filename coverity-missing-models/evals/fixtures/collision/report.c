/* The escape caused by a model that is present but wrong. This project's
 * error() logs and returns. Coverity ships a built-in model for a function
 * named error() that ends the path, and built-in models take precedence
 * over models derived from the code, so the analyzer believes error()
 * never returns and prunes every path through it.
 * No system headers: captured with bare cov-emit --c. */

void log_msg(const char *msg);

void error(const char *msg)
{
    log_msg(msg);                   /* and returns */
}

int first_char(const char *s)
{
    if (s == 0)
        error("first_char: null argument");
    return s[0];                    /* a real defect, hidden by the built-in model */
}
