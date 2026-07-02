"""pyre.adapters — clients for external HTTPS APIs, outcall-hazard-aware.

These wrap pyre's HTTPS outcalls with each service's auth and REST
conventions, and are designed around the platform facts:

  - one canister outcall fans out to ~node-count upstream requests
    (measured 13x on a 13-node subnet), so WRITES MUST BE IDEMPOTENT;
  - only GET/HEAD/POST reach upstream;
  - responses ride a determinism transform;
  - ~2s consensus latency per call.

Standing rule: integration, not hot path. Your real datastore is
pyre.data over stable memory; adapters are for syncing with systems
that live outside the IC.
"""

from pyre.adapters import supabase, upstash  # noqa: F401
