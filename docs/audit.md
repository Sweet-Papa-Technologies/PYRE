# Dependency and build audit

Run the offline audit before a Kybra build:

```bash
pyre audit requirements.txt --canister src --strict
pyre audit --canister src --format json --output audit.json
```

The JSON schema is version 1. Exit 0 means no blocking result, 1 is a strict
warning failure, 2 is definite incompatibility, and 3 is a tool/configuration
failure. Findings always contain code, severity, evidence, and remediation.

Offline checks cover pins/direct URLs/editables, host-tool imports, reserved
basenames, and deterministic-execution footguns. The tool never imports or
executes inspected package code and never labels an unknown dependency as
compatible. Online vulnerability checks are not implemented in this milestone;
network failure must never be interpreted as clean.

CI should fail on any nonzero exit. Treat audit output as compatibility advice,
not a security certification, and continue license and dependency review.

