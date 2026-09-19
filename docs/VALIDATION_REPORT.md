# Specification validation record

This records checks on the planning artifacts before handoff. Runtime backend validation is recorded separately in [BACKEND_REVIEW.md](../BACKEND_REVIEW.md).

Executed docs/tools/validate_spec.py successfully:

- 22 API operations and 52 schemas: local references resolve and schema definitions validate.
- Network, baseline search request/response and preset events conform to the agreed JSON schemas.
- Nine nodes and ten directed lanes have valid IDs/references and resolvable time zones.
- All three baseline timelines have continuous timestamps, correct minute totals, reason contributions and deterministic route hashes.
- An independent, limited fixture replay checks schedule/time arithmetic for all eight scenario cases, including traffic, manager handling delay, temporary closure, cut-off equality, missed cut-off, Sunday pause and Istanbul air/road hand-over.

The replay intentionally handles the simple fixture paths only. It does not validate a production search algorithm, the full event-composition fixed point, HTTP implementation, stale approvals, database transactions or GUI behavior. Those remain mandatory checks in ACCEPTANCE_TESTS.md during implementation.

Rerun from repository root after changing the contract or fixtures:

```
python -m pip install jsonschema
python docs/tools/validate_spec.py
```

Also review semantic changes together: a schema check cannot determine whether a new scheduling assumption is operationally sensible.
