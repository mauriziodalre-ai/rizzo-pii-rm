# RM exact-surface fork

This fork preserves the exact surface forms needed for reversible text
sanitisation in RISKMaiSTER's proof of concept. It is based directly on
Rizzo-AI-Academy/rizzo-pii commit
`9057eeff88bdf0444e5d3361cf0766b60c5b8a95`, with upstream history retained.
The intended repository is `mauriziodalre-ai/rizzo-pii-rm`; this identity does not
assert that a release has been published or approved for runtime use.

The `rm-exact-surface-v1` contract changes only these behaviours:

- Nonblank JSON `POST /analyze` input retains leading and trailing whitespace.
  Blank input still returns 400; uploaded text keeps its existing trim behaviour.
- The actual selected substring and tag determine each placeholder. Case,
  whitespace and Unicode composition variants receive distinct placeholders;
  repeated identical values with the same tag reuse their placeholder. Mapping
  values remain exact source slices. Mapping-disabled output still returns an
  empty mapping and omits source text and original entity preview values.
- `/health` and `/healthz` retain existing fields/statuses and add
  `rm_fork_repository`, `rm_upstream_commit` and `rm_surface_contract` from
  `src/app/rm_fork_identity.py`.

Span selection, word-boundary handling, overlap priority, chunk offsets, regex
detectors, PDF modules, preference handling, tag inventory, upstream version
strings and dependencies are unchanged. Model weights and training are
unchanged; the RM integration continues to pin model revision
`a1c3c83827eca22e9675e30c1111c4641caf5901` separately. This patch does not promise
detection recall or change which spans upstream chooses to mask. JSON text is
the proof-of-concept interface; other PDF/UI routes retain upstream behaviour.

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
The existing suite may skip dependency-gated tests in this stdlib environment;
report skips explicitly instead of claiming full runtime coverage.

## Provenance, licensing and runtime gates

`LICENSE` and `THIRD_PARTY_LICENSES.md` remain byte-identical to upstream.
Preserve their MIT and third-party notices and the upstream history when
publishing. Exact release commit, source archive hash, changed-file hashes,
test evidence and notice hashes belong in the external RM provenance record;
the identity module deliberately does not embed its own eventual commit hash.

The upstream model/dependency licences, including PyMuPDF and the actual
resolved dependency inventory, require a separate owner decision. Source
publication is not a legal or commercial runtime verdict. The RM
`liveRunAllowed` gate stays false until separately approved. Health identity
strings are declarations, not immutable source/runtime attestation; the RM
build must still bind published source, model/base/runtime pins and baked
filesystem hash evidence. No test here authorizes a Mini, container, Funnel or
provider execution, or replaces the guarded live readiness and no-AI smoke.
