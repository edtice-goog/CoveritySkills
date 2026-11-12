/* error() returns. A user model takes precedence over the built-in model
 * of the same name, so this restores the function's real behaviour. It
 * calls the external it really calls, so nothing the code does is lost. */
void log_msg(const char *msg);

void error(const char *msg)
{
    log_msg(msg);
}
