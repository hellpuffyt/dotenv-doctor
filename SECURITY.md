# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's advisory form:
<https://github.com/hellpuffyt/dotenv-doctor/security/advisories/new>

Please do not open a public issue for a vulnerability, and never include a
real credential in a report — build a synthetic value of the same shape.

Especially in scope: any path by which a value from a checked file reaches
stdout, stderr, JSON or GitHub output (including error messages and
tracebacks); workflow-command injection through file names or keys; any
network access.

A credential shape that is not detected is a detection gap; a normal issue
with a synthetic example is fine for those.

## Supported versions

Only the latest release on the default branch receives fixes.
