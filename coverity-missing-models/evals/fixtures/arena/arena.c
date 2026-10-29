/* The escaped-defect case. An arena allocator: an arena's header lives in
 * its own first block, objects are carved out of its blocks, and destroying
 * an arena returns its blocks to a private free list instead of releasing
 * them. A doc lives in an arena of its own, and doc_close() destroys it.
 * No system headers: captured with bare cov-emit --c. */

typedef unsigned long arena_size_t;
void *malloc(arena_size_t n);       /* only for fresh blocks */

#define BLOCK_BYTES 4096
#define MAX_ALLOC   1024

struct block {
    struct block *next;
    char *avail;
    char *end;
};

struct arena {
    struct block *blocks;           /* the last of them holds this header */
    struct arena *parent;
    struct arena *subs;             /* first child arena */
    struct arena *sub_next;         /* next sibling in parent->subs */
};

static struct block *free_blocks;

static struct block *new_block(void)
{
    struct block *b = free_blocks;

    if (b != 0) {
        free_blocks = b->next;
    } else {
        b = (struct block *)malloc(BLOCK_BYTES);
        if (b == 0)
            return 0;
        b->end = (char *)b + BLOCK_BYTES;
    }
    b->next = 0;
    b->avail = (char *)(b + 1);
    return b;
}

void *arena_alloc(struct arena *a, arena_size_t n)
{
    struct block *b;
    char *p;

    if (a == 0 || n == 0 || n > MAX_ALLOC)
        return 0;
    n = (n + 15) & ~(arena_size_t)15;
    b = a->blocks;
    if ((arena_size_t)(b->end - b->avail) < n) {
        b = new_block();
        if (b == 0)
            return 0;
        b->next = a->blocks;
        a->blocks = b;
    }
    p = b->avail;
    b->avail += n;
    return p;
}

void *arena_calloc(struct arena *a, arena_size_t n)
{
    char *p = (char *)arena_alloc(a, n);
    arena_size_t i;

    if (p != 0)
        for (i = 0; i < n; i++)
            p[i] = 0;
    return p;
}

struct arena *arena_create(struct arena *parent)
{
    struct block *b = new_block();
    struct arena *a;

    if (b == 0)
        return 0;
    a = (struct arena *)b->avail;
    b->avail += sizeof(struct arena);
    a->blocks = b;
    a->parent = parent;
    a->subs = 0;
    a->sub_next = 0;
    if (parent != 0) {
        a->sub_next = parent->subs;
        parent->subs = a;
    }
    return a;
}

void arena_destroy(struct arena *a);

/* Destroys every child arena. Each arena_destroy() unlinks its argument
 * from a->subs, so the loop advances. */
void arena_clear(struct arena *a)
{
    while (a->subs != 0)
        arena_destroy(a->subs);
}

void arena_destroy(struct arena *a)
{
    struct block *b, *next;

    if (a == 0)
        return;
    arena_clear(a);
    if (a->parent != 0) {
        struct arena **pp = &a->parent->subs;
        while (*pp != a)
            pp = &(*pp)->sub_next;
        *pp = a->sub_next;
    }
    for (b = a->blocks; b != 0; b = next) {
        next = b->next;
        b->next = free_blocks;
        free_blocks = b;
    }
}

/* An object that owns its arena: it is the arena's first allocation. */
struct doc {
    struct arena *arena;
    int len;
};

struct doc *doc_open(struct arena *parent)
{
    struct arena *a = arena_create(parent);
    struct doc *d;

    if (a == 0)
        return 0;
    d = (struct doc *)arena_calloc(a, sizeof(struct doc));
    if (d == 0) {
        arena_destroy(a);
        return 0;
    }
    d->arena = a;
    return d;
}

void doc_close(struct doc *d)
{
    if (d == 0)
        return;
    arena_destroy(d->arena);
}

int use_after_close(struct arena *top)
{
    struct doc *d = doc_open(top);

    if (d == 0)
        return -1;
    d->len = 3;
    doc_close(d);
    return d->len;                  /* the defect: d went with its arena */
}

int twin(struct arena *top)
{
    struct doc *d = doc_open(top);
    struct doc *e = doc_open(top);
    int n;

    if (d == 0 || e == 0)
        return -1;
    e->len = 4;
    doc_close(d);
    n = e->len;                     /* the canary: e is alive, must stay silent */
    doc_close(e);
    return n;
}
