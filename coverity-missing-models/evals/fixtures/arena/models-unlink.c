/* The primitive again, keeping the side effect the bare version drops:
 * arena_destroy() unlinks its argument from the parent's list of children
 * before releasing it. */
struct block;

struct arena {
    struct block *blocks;
    struct arena *parent;
    struct arena *subs;
    struct arena *sub_next;
};

void arena_destroy(struct arena *a)
{
    if (a == 0)
        return;
    if (a->parent != 0 && a->parent->subs == a)
        a->parent->subs = a->sub_next;
    __coverity_free__(a);
}
