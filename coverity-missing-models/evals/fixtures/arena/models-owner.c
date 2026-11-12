/* The owner: doc_close() releases the doc, because the doc is the first
 * allocation of the arena it destroys. Invariant: doc_open() allocates the
 * doc from d->arena (enforced in doc_open). Broken by: a doc allocated
 * from any other arena. */
struct doc;

void doc_close(struct doc *d)
{
    if (d == 0)
        return;
    __coverity_free__(d);
}
