/* fail_hard() ends the path: it reaches exit through a hook the analyzer
 * cannot follow. Invariant: exit_hook is installed before any caller runs
 * and never returns (enforced at startup). Broken by: a hook that returns,
 * or a call to fail_hard() before the hook is installed. */
void fail_hard(const char *msg)
{
    __coverity_panic__();
}
