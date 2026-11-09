# RM exact-surface fork

This fork preserves the exact surface forms needed for reversible text
sanitisation in RISKMaiSTER's proof of concept. It is based directly on
Rizzo-AI-Academy/rizzo-pii commit
`9057eeff88bdf0444e5d3361cf0766b60c5b8a95`, with upstream history retained.
The intended repository is `mauriziodalre-ai/rizzo-pii-rm`; this identity does not
assert that a release has been published or approved for runtime use.

The `rm-exact-surface-v1` contract changes only these behaviours:

- Nonblank JSON `POST /analyze` input retains leading and trailing whitespace.
  Blank input still returns 400. Multipart and document uploads are unsupported.
- The actual selected substring and tag determine each placeholder. Case,
  whitespace and Unicode composition variants receive distinct placeholders;
  repeated identical values with the same tag reuse their placeholder. Mapping
  values remain exact source slices. Mapping-disabled output still returns an
  empty mapping and omits source text and original entity preview values.
- `/health` and `/healthz` retain existing fields/statuses and add the immutable
  RM fork, span-contract and text-only runtime-profile identity fields from
  `src/app/rm_fork_identity.py`.

Span selection, word-boundary handling, overlap priority, chunk offsets, regex
detectors, preference handling, tag inventory and upstream version strings are
unchanged. The unused text `_norm` helper was removed.
Model weights and training are
unchanged; the RM integration continues to pin model revision
`a1c3c83827eca22e9675e30c1111c4641caf5901` separately. This patch does not promise
detection recall or change which spans upstream chooses to mask.

The additive `rm-span-surface-v1` contract exposes only `POST /rm/spans` for
JSON text input. It executes the same model, regex/checksum, exclusion, overlap,
whitespace-trim and word-boundary path that `/analyze` uses before placeholder
creation. The response contains Python code-point offsets, tag, score, source,
the SHA-256 of the exact received UTF-8 text and the contract identifier. It
contains no source text, mapping, placeholder, anonymized text, preview or
detected value. Regex spans report a null score; model spans report the selected
model score. Leading/trailing whitespace and Unicode composition are not
normalized. Blank input still returns 400.

`/analyze`, its response and the existing `rm-exact-surface-v1` contract remain
unchanged. `/health` and `/healthz` add `rm_span_contract` alongside the existing
fork identity fields.

RM release support covers JSON text `POST /analyze`, `POST /rm/spans`, read-only
`GET /settings` and their additive health identity only. PDF, document-upload
and UI routes are closed by the RM text-only boundary before route dispatch and
their runtime handlers have been removed. Multipart requests, settings mutation,
configuration routes, document caches and PDF export/preview are absent. PyMuPDF
is not installed or loaded; the runtime also does not import `pdf_export` or
`pdf_text`. Non-JSON text calls receive a fixed 415; unavailable routes and
methods receive a fixed 404. `HEAD` is retained only for health probes. Read-only
settings omit the host preference path. Health exposes
`rm_runtime_profile=rm-text-only-v1` so the proxy
can refuse an older full-document image. The dormant upstream PDF source remains
in the published history only for auditability and is not part of the RM runtime
contract.

This RM release publishes only the containerized text service. Upstream
Windows/macOS/Linux desktop and Tauri packaging definitions are intentionally
removed: their browser UI depends on the retired document routes and must not be
distributed from this branch. The container copies an explicit four-file runtime
allowlist, so dormant PDF helpers do not enter the image.

## Offline tests

From the repository root, with Python 3.11 and no additional packages:

```sh
PYTHONDONTWRITEBYTECODE=1 python3.11 -m unittest discover -s tests -p 'test_rm_exact_surface.py' -v
PYTHONDONTWRITEBYTECODE=1 python3.11 -m unittest discover -v tests
```

The new stdlib harness compiles the actual named function bodies from `app.py`
by AST, removing route decorators only. It injects request/config dependencies
and uses fixed candidates or fake inference outputs. The overlap/chunk tests
execute actual `_merge`, `chunk_text`, `detect_model` and `analyze`, including
global offsets and duplicate detections from overlapping chunks. It does not
import the model startup path, download models, perform inference or start a
server. Fixed vectors and independent one-pass restoration check UTF-8 byte
equality. Assertion failures use stable codes rather than text/mapping dumps.
Document-upload and PDF-runtime tests are intentionally excluded from this
release because those surfaces no longer exist. Dependency-gated model/app tests
that remain in the suite are reported explicitly rather than being represented
as runtime coverage.

## Provenance, licensing and runtime gates

`LICENSE` and `THIRD_PARTY_LICENSES.md` remain byte-identical to upstream.
Preserve their MIT and third-party notices and the upstream history when
publishing. Exact release commit, source archive hash, changed-file hashes,
test evidence and notice hashes belong in the external RM provenance record;
the identity module deliberately does not embed its own eventual commit hash.

The upstream model and actual resolved text-runtime dependency inventory require
a separate owner decision. PyMuPDF is excluded from the RM runtime rather than
accepted as an unused dependency. Source
publication is not a legal or commercial runtime verdict. The RM
`liveRunAllowed` gate stays false until separately approved. Health identity
strings are declarations, not immutable source/runtime attestation; the RM
build must still bind published source, model/base/runtime pins and baked
filesystem hash evidence. No test here authorizes a Mini, container, Funnel or
provider execution, or replaces the guarded live readiness and no-AI smoke.
