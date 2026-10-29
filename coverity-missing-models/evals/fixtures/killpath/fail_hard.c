/* The false-positive case. fail_hard() ends the process through a hook
 * installed at startup, so the analyzer cannot see that it never returns,
 * and treats a check followed by fail_hard() as a path that carries on.
 * (The name matters: a function named fatal(), die() or error() would get
 * Coverity's built-in killpath model instead of its own; see ../collision.)
 * No system headers: captured with bare cov-emit --c. */

typedef void (*exit_fn)(int);
exit_fn exit_hook;                  /* installed at startup; never returns */
void log_msg(const char *msg);

void fail_hard(const char *msg)
{
    log_msg(msg);
    exit_hook(1);
}

int first_char(const char *s)
{
    if (s == 0)
        fail_hard("first_char: null argument");
    return s[0];                    /* the false positive: fail_hard() never returns */
}

int first_char_logged(const char *s)
{
    if (s == 0)
        log_msg("first_char_logged: null argument");
    return s[0];                    /* a real defect of the same shape: must survive the model */
}
