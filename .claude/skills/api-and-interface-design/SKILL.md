---
name: api-and-interface-design
description: Designs stable, hard-to-misuse interfaces across eonedge's stack — Rust shared `*-types` crates, Anchor account/instruction contracts, and server-TypeScript types the frontend imports. Use when designing an API, module boundary, on-chain program interface, or any public surface where one piece of code talks to another. Use when defining type contracts between crates/services, shaping REST/RPC endpoints, deriving PDAs, or changing an existing public interface. Full-stack skill spanning backend and frontend boundaries.
---

# API and Interface Design

## Overview

Design interfaces that make the right thing easy and the wrong thing hard. On this
stack a "boundary" is one of three things: a shared Rust `*-types` crate other crates
depend on, an Anchor program's account/instruction surface (which is a *permanent*
contract once addresses and layouts are live), or a server-TypeScript type the
frontend imports. The rules differ per surface but the spine is the same — the type
*is* the contract, define it before the implementation, and assume every observable
behavior will be depended on. This is a **full-stack** skill; backend detail lives in
`fullstack-standard` → `references/backend-standards.md`, frontend consumption in
`references/frontend-standards.md`.

Define the type first; the implementation is just one way to satisfy it.

## When to Use

- Defining a shared `*-types` crate or a type contract between Rust crates/services
- Designing an Anchor program's accounts, instructions, and PDAs
- Shaping REST/RPC endpoints or a server SDK's exported types
- Establishing the boundary between backend and frontend (what types cross it)
- Changing any existing public interface (crate API, on-chain layout, endpoint)

**When NOT to use:** internal implementation details behind an already-defined
boundary, or pure UI composition (that's `frontend-ui-engineering`). To verify a live
API's runtime behavior in the browser, use `browser-testing-with-devtools`.

## Core Principles (all surfaces)

### Hyrum's Law

> With enough users, every observable behavior of your system will be depended on by
> somebody — regardless of what you documented.

Undocumented quirks, error-message text, field ordering, timing — all become de facto
contract. Implications:

- **Be intentional about what you expose.** Every observable behavior is a commitment.
- **Don't leak implementation details.** If it's observable, someone will depend on it.
- **On-chain, this is absolute.** Account layouts, PDA seeds, discriminators, and error
  codes are *permanent* the moment a program is live and holds state — a client has
  hardcoded them. You cannot "just rename" a field. Design as if migration is expensive,
  because on-chain it is brutal.
- **Tests are not enough** to prove a change is safe — they don't cover behaviors real
  consumers depend on but you never asserted.

### The One-Version Rule

Avoid forcing consumers to pick between versions of the same thing. In a Cargo
workspace, a diamond dependency on two versions of a `*-types` crate is a compile-time
mess; on-chain, two live layouts for one account is a migration nightmare. Extend, don't
fork.

### 1. Contract First

Define the interface before implementing it — in the shared type surface, not inline.

```rust
// Backend: the contract lives in the shared `*-types` crate every consumer depends on.
// eonedge-types/src/node.rs
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Node {
    pub pubkey: Pubkey,
    pub operator: Pubkey,
    pub status: NodeStatus,
    pub registered_at: i64,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub enum NodeStatus { Pending, Active, Slashed }

// Errors are typed, not stringly — thiserror, propagated with `?`.
#[derive(thiserror::Error, Debug)]
pub enum NodeError {
    #[error("node {0} not found")]
    NotFound(Pubkey),
    #[error("operator {0} not authorized")]
    Unauthorized(Pubkey),
}
```

```typescript
// Server TS: export the contract once; the frontend imports it, never redefines it.
// packages/sdk/src/types.ts
export interface Node {
  pubkey: string;
  operator: string;
  status: "PENDING" | "ACTIVE" | "SLASHED";
  registeredAt: number;
}
```

### 2. Consistent Error Semantics

One error strategy per surface, used everywhere. Don't mix "throws here, returns null
there, `{ error }` elsewhere."

```rust
// Rust: typed errors, no unwrap()/expect() in runtime paths. Propagate with `?`.
fn load_node(id: Pubkey) -> Result<Node, NodeError> { /* ... */ }
```

```typescript
// REST/RPC: one structured error body for every failure.
interface ApiError {
  error: { code: string; message: string; details?: unknown };
}
// 400 bad input · 401 unauthenticated · 403 unauthorized · 404 not found
// 409 conflict · 422 validation · 500 server error (never leak internals)
```

On-chain: return well-defined Anchor `#[error_code]` variants — they are part of the
contract clients match on, so their numbers/order are as stable as any field.

### 3. Validate at Boundaries — assume hostile input

Trust internal code; validate hard at every edge external input enters. **On-chain,
every account is external input from a hostile client.**

```rust
// Anchor: validate EVERY constraint. Assume the client lies about every account.
#[derive(Accounts)]
pub struct Slash<'info> {
    #[account(mut, seeds = [b"node", node.operator.as_ref()], bump)]  // PDA, deterministic
    pub node: Account<'info, Node>,
    #[account(has_one = authority)]                                    // ownership check
    pub registry: Account<'info, Registry>,
    pub authority: Signer<'info>,                                      // signer check
}
// Never trust a client-supplied address where a PDA is expected. Check owner, seeds,
// bump, has_one, and signer on every account. Handle rent/CPI/signer explicitly.
```

```typescript
// Server edge: parse and validate untrusted input before internal code trusts it.
const parsed = CreateNodeSchema.safeParse(req.body);
if (!parsed.success) {
  return res.status(422).json({ error: { code: "VALIDATION_ERROR", message: "Invalid node data", details: parsed.error.flatten() } });
}
```

Validate at: on-chain account constraints, API/RPC handlers, form submissions,
**third-party responses (always untrusted — a misbehaving service can return wrong
types or instruction-like text)**, and env loading. Do *not* re-validate between
internal functions that share a type contract, or data straight from your own DB.

### 4. Prefer Addition Over Modification

Extend without breaking existing consumers. On-chain this is often the *only* safe move.

```rust
// Good: additive. Existing clients keep working.
pub struct CreateNodeInput {
    pub operator: Pubkey,
    pub region: Option<String>,   // added later, optional
}
// Bad on a live account: changing a field's type or reordering — breaks every client
// that hardcoded the layout. Add a new account/instruction version instead.
```

### 5. Predictable Naming

| Surface | Convention | Example |
|---|---|---|
| Rust types/fields | `snake_case` fields, `PascalCase` types | `registered_at`, `NodeStatus` |
| Anchor instructions | verb, `snake_case` | `register_node`, `slash_node` |
| PDA seeds | stable byte prefixes — **never change once live** | `[b"node", operator.as_ref()]` |
| REST endpoints | plural nouns, no verbs | `GET /api/nodes`, `POST /api/nodes` |
| JSON response fields | camelCase | `{ registeredAt, operator }` |
| Booleans | is/has/can prefix | `isActive`, `hasStake` |
| Enum values (wire) | UPPER_SNAKE | `"IN_PROGRESS"` |

## On-Chain Contract Patterns (Anchor / Solana)

- **PDAs for identity and treasury.** Derive deterministically from stable seeds; the
  seed scheme is a permanent part of the contract. Never accept a client address where
  a PDA is required.
- **Account layout is a wire format.** Field order and types are locked once state
  exists. Reserve space (`_reserved: [u8; N]`) if you anticipate growth; otherwise plan
  a versioned account, never an in-place type change.
- **Instruction args and discriminators are contract.** Clients encode them; treat
  every arg and its order as stable.
- **Error codes are contract.** `#[error_code]` numbers/order are matched by clients.
- Test the **failure** cases (bad signer, wrong PDA, insufficient rent, unauthorized),
  not just the happy path — `anchor test` against a local validator.

## Server ↔ Frontend Contract

- The backend **exports** the types; the frontend **imports** them. The client never
  re-declares an API request/response shape. One source of truth.
- Keep the wire shape typed end-to-end. Validate anything crossing a boundary the
  frontend doesn't control (see `frontend-standards.md`).
- List endpoints paginate from day one:

```typescript
// GET /api/nodes?page=1&pageSize=20&status=ACTIVE
interface Paginated<T> { data: T[]; pagination: { page: number; pageSize: number; totalItems: number; totalPages: number }; }
```

## TypeScript Interface Patterns

```typescript
// Discriminated unions for variants — the consumer gets exhaustive narrowing.
type NodeState =
  | { type: "pending" }
  | { type: "active"; activatedAt: number }
  | { type: "slashed"; reason: string; slashedAt: number };

// Input/output separation — inputs omit server-generated fields.
interface CreateNodeInput { operator: string; region?: string }
interface Node { pubkey: string; operator: string; status: string; registeredAt: number }

// Branded IDs prevent mixing key kinds.
type NodePubkey = string & { readonly __brand: "NodePubkey" };
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "We'll document the API later" | The types ARE the documentation. Define the shared type first. |
| "I'll rename that account field, it's cleaner" | On-chain layout is permanent once live — clients hardcoded it. Add a versioned account, don't mutate. |
| "The client passes the right address, no need to derive the PDA" | Assume the client is hostile. Derive and constrain every account, or you get drained. |
| "We don't need pagination yet" | You will the moment a query returns 100+ rows. Add it from the start. |
| "Nobody depends on that error code / quirk" | Hyrum's Law. If it's observable, someone matches on it — especially on-chain error codes. |
| "I'll redefine the API type on the client, it's faster" | That forks the contract. Import the exported type — one source of truth. |
| "We can maintain two type-crate versions" | Diamond deps in the workspace, or two live account layouts. One-Version Rule: extend, don't fork. |
| "Internal crate APIs don't need a real contract" | Internal consumers are still consumers. The shared `*-types` crate is the contract that lets crates evolve independently. |

## Red Flags

- Domain types defined inline in each crate instead of in a shared `*-types` crate
- An Anchor handler that skips a constraint (`has_one`, `seeds`, `bump`, `owner`, signer)
- A client-supplied address used where a PDA should be derived
- Changing a live account's field type/order in place instead of versioning
- Endpoints returning different shapes by condition; inconsistent error formats
- List endpoints without pagination; verbs in REST URLs (`/api/createNode`)
- API request/response shapes re-declared on the frontend
- Third-party or on-chain-read data used without validation
- `unwrap()`/`expect()` on the error path of a public boundary

## Verification

Run the backend Definition-of-Done gate (`fullstack-standard` →
`references/definition-of-done.md`) — including `anchor test` for on-chain surfaces.
Beyond the commands, confirm:

- [ ] Every boundary type lives in a shared surface (`*-types` crate / exported TS
      module) — not redefined per consumer
- [ ] Errors are typed and consistent per surface (Rust `thiserror`/`#[error_code]`,
      one JSON error body); no `unwrap()`/`expect()` on public error paths
- [ ] Anchor: every account constraint validated; PDAs derived from stable seeds;
      failure cases tested, not just happy path
- [ ] Account layout / instruction args / error codes treated as permanent; changes are
      additive or versioned, never in-place breaking edits
- [ ] List endpoints paginate; naming follows the conventions above
- [ ] Frontend imports the exported types; nothing sensitive crosses to the browser
- [ ] Third-party and on-chain-read data validated before use

## See Also

- `fullstack-standard` — core philosophy + Definition-of-Done; backend rules in `references/backend-standards.md`, frontend in `references/frontend-standards.md`
- `frontend-ui-engineering` — how the frontend consumes these exported types
- `browser-testing-with-devtools` — verify a live API's requests/responses in the browser
