/* The primitive: arena_destroy() releases the arena. Faithful for the
 * arena header, which lives in the arena's own blocks. */
struct arena;

void arena_destroy(struct arena *a)
{
    if (a == 0)
        return;
    __coverity_free__(a);
}
