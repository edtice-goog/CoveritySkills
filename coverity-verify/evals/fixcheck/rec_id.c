/* The helper the silencing change moved the dereference into. It is NOT in
 * the capture (think: a library the build links but does not compile), so
 * the analyzer has no model for it and sees no dereference. In a fix check
 * it is real code: a callee the change introduced is never stubbed, because
 * a stub for it would be as blind as the analyzer was. The harness carries
 * this body. */
struct rec { int id; int value; };
int rec_id(struct rec *r) { return r->id; }
