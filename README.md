# GradeCompass

Proof-of-concept demo of a stainless steel grade selector that works backwards from the
environment: enter a location and an application, get a grade, the reasoning, and what that
grade really costs per year of service life.

**Live demo:** https://grv-io.github.io/gradecompass/

- `index.html` — the complete demo (engine inlined, no build step, no server)
- `engine.js` — the recommendation engine as a standalone module, parity-tested 756/756
  against the Python reference implementation

The engine is deterministic end to end — ISO 9223 environment classification, failure-mode
elimination with a hard safety floor, and cost/performance ranking including a ₹/kg →
₹/service-year comparison. Preliminary build on a 12-grade / 12-district subset.
