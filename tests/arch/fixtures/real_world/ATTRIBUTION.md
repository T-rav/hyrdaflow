# Real-World Extractor Fixture Attribution

These fixtures are small vendored snapshots of real open-source repositories, used
to integration-test the `tree_sitter_extractor` against non-trivial code.

Each language snapshot is ≤ 20 files and ≤ 50 KB total. The LICENSE file of the
upstream project is vendored alongside the source files.

---

## Python — theskumar/python-dotenv

- **Repo:** https://github.com/theskumar/python-dotenv
- **Commit SHA:** `bca6644d9aedbe287b792b756b3ae3d650cd0d3a`
- **License:** MIT
- **Files vendored:** `src/dotenv/__init__.py`, `src/dotenv/main.py`,
  `src/dotenv/parser.py`, `src/dotenv/variables.py`, `LICENSE`
- **Extractor finding:** The Python extractor captures the full
  `import_from_statement` node text (e.g., `"from .main import foo"`). Because
  this text doesn't start with `.`, `_resolve_relative` returns `None`, and the
  fallback `stems.get(spec.split("/")[-1].split(".")[0])` receives `"from "` (with
  a trailing space), which never matches a file stem. As a result, **all relative
  imports produce zero edges**. This is a known limitation of the current Python
  extractor — the node capture should extract only the module path token, not the
  entire statement. Filed as a follow-up.

---

## TypeScript — supermacro/neverthrow

- **Repo:** https://github.com/supermacro/neverthrow
- **Commit SHA:** `5ef3a018bda74fb960e44b68fc3672635ee8037d`
- **License:** MIT
- **Files vendored:** `src/index.ts`, `src/result.ts`, `src/result-async.ts`,
  `src/_internals/error.ts`, `src/_internals/utils.ts`, `LICENSE`
- **Extractor finding:** Works correctly. 5 nodes, 7 edges. Relative imports like
  `import { ... } from './result'` resolve properly. No false edges observed.

---

## JavaScript — sindresorhus/execa (lib/arguments subset)

- **Repo:** https://github.com/sindresorhus/execa
- **Commit SHA:** `f3a2e8481a1e9138de3895827895c834078b9456`
- **License:** MIT
- **Files vendored:** `lib/arguments/command.js`, `lib/arguments/cwd.js`,
  `lib/arguments/encoding-option.js`, `lib/arguments/escape.js`,
  `lib/arguments/fd-options.js`, `lib/arguments/file-url.js`,
  `lib/arguments/options.js`, `lib/arguments/shell.js`,
  `lib/arguments/specific.js`, `LICENSE`
- **Note:** Only the `lib/arguments/` subdirectory was vendored (9 files). The
  full execa repo has 50+ files; this subset was chosen because the files
  cross-import each other using ESM `import` statements with relative paths.
- **Extractor finding:** Works correctly for ESM `import` syntax. 9 nodes, 8
  edges. **CJS `require()` calls are NOT captured** — the extractor only handles
  ESM `import_statement` nodes. Libraries using CommonJS will produce zero edges.

---

## Go — hashicorp/go-multierror

- **Repo:** https://github.com/hashicorp/go-multierror
- **Commit SHA:** `6d4d48630db25c3c83fa83ecd41dd8438b82963c`
- **License:** MPL-2.0
- **Files vendored:** `multierror.go`, `append.go`, `flatten.go`, `format.go`,
  `prefix.go`, `sort.go`, `group.go`, `go.mod`, `LICENSE`
- **Extractor finding:** Go module unit is `directory`. All 7 `.go` files live in
  the repository root, so all resolve to the single node `"."`. All imports are
  standard-library (`errors`, `fmt`, `sort`) — none resolve to internal paths.
  Result: 1 node (`"."`), 0 edges. This is correct behaviour for a single-package
  library with no sub-packages and only external/stdlib imports. **Zero internal
  edges is expected** for this fixture.

---

## Java — synthesized

- **Repo:** N/A — synthesized
- **License:** MIT (fixture-local)
- **Inspiration:** Functional-result-type pattern common in Java libraries (e.g.,
  `vavr-io/vavr`). Not copied from any upstream file.
- **Files vendored:** `src/main/java/com/example/result/Result.java`,
  `src/main/java/com/example/result/Success.java`,
  `src/main/java/com/example/result/Failure.java`, `LICENSE`
- **Why synthesized:** No suitably-tiny MIT/Apache Java library with 3–5 files and
  clear cross-file imports was found. `vavr`, `Optional`, and similar projects all
  exceed 20 files or have complex build setups. A synthesized 3-class example gives
  reproducible, license-clean coverage.
- **Extractor finding:** The Java extractor query `(import_declaration (scoped_identifier) @src)`
  captures the full dotted name (e.g., `"com.example.result.Success"`). The
  fallback `stems.get(spec.split("/")[-1].split(".")[0])` extracts `"com"` — the
  first package segment, not the class name — so no stem match occurs. Result: 3
  nodes, 0 edges. This is a known extractor limitation: the scoped identifier
  should be split on `.` to get the last segment (the class name) and matched
  against file stems. Filed as a follow-up.

---

## Rust — dtolnay/itoa

- **Repo:** https://github.com/dtolnay/itoa
- **Commit SHA:** `af77385d0daf4d0e949e81f2588be2e44f69f086`
- **License:** MIT and Apache-2.0 (dual-licensed); MIT file vendored
- **Files vendored:** `src/lib.rs`, `src/u128_ext.rs`, `Cargo.toml`, `LICENSE`
- **Extractor finding:** The Rust extractor query `(use_declaration) @i` captures
  `use` statements but NOT `mod` declarations. The relationship `lib.rs` → `u128_ext.rs`
  is declared via `mod u128_ext;` (a `mod_item` AST node), which is not matched by
  the query. Additionally, even if `use` statements were resolved, the text
  `"use core::hint;"` cannot map to a file path via the current
  `stems.get(spec.split("/")[-1].split(".")[0])` fallback since the spec contains
  spaces and Rust module paths use `::` not `/`. Result: 2 nodes, 0 edges. The
  extractor should add a `(mod_item name: (identifier) @src)` query to capture
  internal module declarations. Filed as a follow-up.

---

## Ruby — ruby/rake (lib subset)

- **Repo:** https://github.com/ruby/rake
- **Commit SHA:** `d9f85ffd9412df0175ec66ba28d682b40c8f3914`
- **License:** MIT
- **Files vendored:** `lib/rake.rb`, `lib/rake/version.rb`, `lib/rake/task.rb`,
  `lib/rake/invocation_exception_mixin.rb`, `lib/rake/dsl_definition.rb`,
  `lib/rake/file_utils_ext.rb`, `LICENSE`
- **Note:** Only `lib/rake.rb` plus 5 small sibling files from `lib/rake/` were
  vendored. The full rake `lib/` has 40+ files; this subset preserves a connected
  subgraph of `require_relative` edges.
- **Extractor finding:** Works correctly for `require_relative` calls. 6 nodes,
  6 edges. Stem-based resolution (e.g., `require_relative "rake/version"` → stem
  `"version"` → `lib/rake/version.rb`) works when only one file has that stem.
  No false edges observed.
