# Writing a path-insensitive candidate checker in CodeXM

The reference is `doc/en/cov_codexm.html` in the installation. It is
written for exact readers: every pattern has its property table, every
expression its grammar, and the compiler's error messages list the
properties a value actually has. Read it there; this page is what the
reference does not say, learned by making the checker in
`evals/escape-hunt/null_check_then_deref.cxm` compile and match.

## The skeleton

```
include `C/C++`;

function helper(e : expression) : bool -> ...;

checker {
    name = "PATHOUT_CANDIDATE_<SHAPE>";
    reports = for d in globalset allFunctionCode
        where <the shape, in terms of d>
        : { events = [ { description = "..."; location = d.location; } ]; };
};
```

`allFunctionCode` is every node of every function. The loop variable is the
node the event is placed on, so make it the *consequence* of the shape (the
dereference), and find the *cause* (the null test) from it. Run with:

```bash
cov-analyze --dir <idir> --disable-default --codexm shape.cxm
```

`--disable-default` leaves only your checker, so the output is candidates
and nothing else. 13 seconds for 9,533 functions.

## What the tree looks like

- `p->f` is a `memberReference` whose `objectExpression` is a
  `pointerDereference` whose `pointerExpression` is the `variableReference`.
  `*p` is the `pointerDereference` alone; `a[i]` is `subscriptReference`
  with `arrayExpression`. Each `p->f` yields two matching nodes (the
  member reference and the dereference under it); the engine reports the
  location once.
- `if (p)` arrives as `if (p != 0)`: a `binaryOperator` with `.operator ==
  \`!=\``, an implicit literal on the right, and `.isImplicit == true`.
  `if (p && p->x)` is a `binaryOperator` `&&` whose `lhsExpression` is that
  implicit `!=`. So one comparison-based test covers `if (p)`, `if (p !=
  NULL)`, `if (p == 0)` and the operands of `&&`/`||`; `!p` is a
  `unaryOperator` with `.operator == \`!\``.
- Casts wrap operands. `stripCasts(e)` removes them; it takes an
  `expression`, so declare the parameter as `expression`, not `astnode`,
  or the compiler says "Cannot convert astnode to expression".
- Variable identity: `variableReference.variable` is a *record*
  (`record[symbol]`), and records do not compare with `==`. Key a variable
  by `v.mangledName ?? v.identifier` (`??` is null-coalescing; `default`
  is a switch keyword, not an operator).
- The function that owns a node: `innermostOwner(functionDefinition, d)`
  is rejected ("Cannot convert functionDefinition to astnode"), and
  `outermostOwner(blockStatement, d)` returns null for an expression. Walk
  `.parent` to the top instead:

  ```
  function root(n : astnode) : astnode ->
      if n.parent matches NonNull as p then root(p) else n endif;
  ```

  and then `allMatchingCodeIn(ifStatement, root(d))` is every `if` in the
  function.
- Containment: `contains(function(x : astnode) -> x == d, s)` answers "is
  node d inside statement s"; node equality works for this.
- Order does not exist. `sourceloc` "has no properties", so nothing can say
  whether the test precedes the dereference. A checker that needs order
  must approximate it structurally (the escaped shape is "outside the
  whole `if`", which needs no order) or accept the noise.

## Grammar that bites

- Every `if` expression ends with `endif`: `if c then a else b endif`.
  `else if` is `elsif`.
- `switch (x) { | pattern as v -> expr | default -> expr }`; the cases are
  expressions, and each `if` inside them still needs its `endif`.
- `where x matches ifStatement` leaves `x` an `astnode`; bind the typed view
  with `as`: `where x matches ifStatement as s` and use `s.trueStatement`.
- A polarity or count is easiest as an `int` return; there is no
  `toString` on ints or enums for building messages, so describe with
  strings and `.formattedAsCode`.
- When a property name is wrong, the error lists the properties the value
  has. Referencing a bogus property on purpose (`d.location.zzz`) is the
  fastest way to see a type's surface.

## The worked example, in prose

`null_check_then_deref.cxm` reports a dereference `d` of variable `v` when
some `if` in the same function tests `v` against null and **nothing guards
`d`**, where "guarded" is structural: `d` is inside an `if` whose condition
tests `v` (either branch; the checker does not know which one is safe),
inside a ternary whose condition tests `v`, on the right of `v && ...` or
of `!v || ...`, or anywhere outside an `if (!v) <exit>` (an exit guard is
taken to cover the whole function, since there is no order). That is the
whole logic: no order, no reassignment, no feasibility.

The first draft required only that `d` be outside *one* testing `if`, and
reported 2,088 sites on subversion, four in five of them dereferences
sitting inside a guard of their own variable that happened to have a second
test elsewhere in the function. The guard definition above took it to 503.
On the fixture it reports the two intended sites and none of the three
controls (call inside the guard, early-return guard, dereference in the
else branch).

Gaps found by reading the survivors, not yet closed:

- a loop condition is not a guard (`for (...; p && i < p->n; ...)` bodies
  are reported);
- `assert(p)` and a call to a `noreturn` function are not exits, only
  `return`/`goto`/`break`/`continue` are;
- two locals with the same name in one function are one variable to the
  checker when the front end supplies no `mangledName` for them.

Derive your own from the escaped instance the same way: write down the
shape in one sentence, encode the sentence, run it on a five-function
fixture with the shape and its nearest non-shapes, and only then on the
idir.
