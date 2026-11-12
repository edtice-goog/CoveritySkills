/* cov-make-library compiles a model with primitives.h already in scope, and
 * primitives.h declares size_t. Declaring it again is an error. */
typedef unsigned long size_t;

void *xalloc(size_t n)
{
    return __coverity_alloc__(n);
}
