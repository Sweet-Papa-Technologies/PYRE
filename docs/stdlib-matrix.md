# Python stdlib support matrix (Kybra 0.7.1 / RustPython → WASM)

Empirical audit run on a deployed canister (`examples/stdlib_audit`, local
replica, dfx 0.32.0, Kybra 0.7.1, deploy venv Python 3.10.7). Every public
module in the host's `sys.stdlib_module_names` (217 modules) was probed with
`__import__` inside the canister. **142 imported cleanly, 75 failed, 0
trapped** (every failure is a clean `ModuleNotFoundError`/`AttributeError`,
not a canister trap).

Method: `dfx canister call stdlib_audit audit_import '("mod1,mod2,...")'` in
batches of 20, plus dedicated probes for determinism footguns and hashlib
correctness (known-answer vectors for `b"abc"`).

> Import success ≠ full functionality. Notable cases where a package imports
> but key submodules fail are called out below (e.g. `email` imports but
> `email.message` does not).

## Works (imports cleanly, no known footgun)

abc, aifc, argparse, array, ast, atexit, base64, bdb, binascii, binhex,
bisect, builtins, calendar, chunk, cmath, cmd, code, codecs, codeop,
collections (+ collections.abc), colorsys, compileall, concurrent
(+ concurrent.futures), configparser, contextlib, contextvars, copy, copyreg,
csv, dataclasses, dbm (+ dbm.dumb), decimal, difflib, dis, distutils, enum,
encodings (+ encodings.idna), errno, fcntl, filecmp, fileinput, fnmatch,
fractions, functools, gc, genericpath, getopt, gettext, glob, graphlib, gzip,
hashlib, heapq, hmac, html, http (top-level only — see broken), imghdr, imp,
importlib (see footgun), inspect, io, ipaddress, itertools, json
(+ json.decoder), keyword, linecache, locale, logging (top-level —
`logging.handlers` broken), marshal, math, mimetypes, netrc, ntpath,
nturl2path, numbers, opcode, operator, optparse, pickle, pickletools,
pkgutil, plistlib, posix, posixpath, pprint, py_compile, pydoc_data, pyexpat,
queue, quopri, re, reprlib, runpy, sched, shlex, sndhdr, sre_compile,
sre_constants, sre_parse, stat, statistics, string, stringprep, struct,
sunau, symtable, sys, sysconfig, tabnanny, tarfile, textwrap, this, timeit,
token, tokenize, trace, traceback, types, typing, unicodedata, urllib
(`urllib.parse` ok; `urllib.request` broken), uu, warnings, weakref, wsgiref
(+ wsgiref.util), xdrlib, xml (+ xml.etree.ElementTree), xmlrpc (top-level),
zipimport, zlib

## Works but FOOTGUN (imports and runs — behavior will surprise you)

Canister code runs replicated: every replica must produce byte-identical
results or consensus fails. RustPython therefore stubs all entropy sources
with **deterministic constants**. These are not merely "same across
replicas" — they are **the same values on every single call**, forever
(measured across repeated query AND update calls):

| Module / call | Observed behavior (actual values) | Verdict |
|---|---|---|
| `random.random()` | Works, but the PRNG restarts identically every message: first call always `0.08576028929936241`, second always `0.304256765543397` — in queries and updates alike | Zero entropy. Use `management_canister.raw_rand()` and seed explicitly if you need a PRNG |
| `uuid.uuid4()` | Returns the SAME uuid every call: `10b0a742-f1e4-4238-a7a4-5cae054ec21c` | Never use for unique IDs. Derive IDs from `ic.time()` + caller + a counter, or from `raw_rand` |
| `os.urandom(8)` | Constant bytes every call: `e0107e1661bac638` | Not random. `raw_rand` only |
| `secrets.token_hex(4)` | Constant every call: `0d5ab832` | **Security-critical**: `secrets` is neither secret nor random here. Any key/token generation MUST go through `raw_rand` |
| `datetime.datetime.now()` | Works; mirrors IC consensus time (e.g. `2026-07-02T20:28:33.233586`) | Deterministic per message (it IS `ic.time()`), advances between messages. Fine for timestamps; do not expect OS wall-clock semantics |
| `time.time()` | Works; equals `ic.time()/1e9` exactly (`1783024113.233586` vs `ic.time()=1783024113233586001` ns) | Same as above. Prefer `ic.time()` (nat64 ns, no float loss) |
| `kybra.ic.time()` | `nat64` nanoseconds since epoch, consensus time | The canonical clock |
| `threading` | Imports, but WASM canisters are single-threaded; no real concurrency | Don't build on it |
| `tempfile`, `shutil`, `glob`, `os` file APIs | Import fine, but the filesystem is the in-WASM virtual FS — not persistent across upgrades, partially stubbed (`os.chmod` missing) | Use `StableBTreeMap` for persistence |
| `getpass`, `logging` | Import; interactive/handler parts are dead ends (`logging.handlers` needs sockets) | Basic `logging` to debug print is fine |
| `shelve` | Imports (via dbm.dumb on virtual FS) | Not durable storage; use stable structures |

## Broken (import fails)

No module trapped the canister; all fail with clean exceptions, grouped by
root cause:

| Root cause | Modules |
|---|---|
| No sockets (`_socket` missing) | socket, socketserver, ssl (`_ssl`), cgi, ftplib, mailbox, nntplib, smtpd, smtplib, telnetlib, poplib, imaplib, **email.message / email.mime.\*** (top-level `email` imports, message classes don't), http.client, http.server, urllib.request, logging.handlers |
| No signals (`_signal` missing) | signal, subprocess, multiprocessing, unittest, doctest, pdb, pydoc, platform, venv, webbrowser, ensurepip, cgitb, antigravity |
| No `select` | select, selectors, asyncio, asynchat, asyncore, pty |
| Missing C extension | sqlite3 (`_sqlite3`), ctypes (`_ctypes`), bz2 (`_bz2`), lzma, mmap, zoneinfo, tracemalloc, faulthandler, readline, curses, tkinter, turtle |
| `os.chmod` not implemented | **pathlib**, zipfile, zipapp, importlib.metadata, importlib.resources |
| Unix-only stubs absent | pwd, grp, spwd, nis, termios, tty, syslog, resource, crypt, ossaudiodev, pipes |
| Windows-only | winreg, winsound, msvcrt, msilib, nt |
| Not bundled / misc | cProfile, profile, pstats, lib2to3, idlelib, modulefinder, pyclbr, mailcap, audioop, wave, turtledemo, site (TypeError at import), rlcompleter (needs `__main__`) |

Notable stings:

- **`pathlib` is broken** (`os.chmod` missing). Framework and example code
  must use `os.path`/`posixpath` inside canisters.
- **`asyncio` is broken** — Kybra's `Async`/generator `yield` pattern is the
  only async model.
- **`zoneinfo` is broken** — no tz database; only naive/UTC datetime math.
- `zlib`/`gzip` work; `bz2`/`lzma` do not.
- `email` and `http` import at top level but their useful submodules die on
  `_socket` — treat both packages as broken.

## hashlib / hmac primitives (known-answer tested with `b"abc"`)

| Primitive | Result |
|---|---|
| md5 | ok (correct digest) |
| sha1 | ok |
| sha224 | ok |
| sha256 | ok |
| sha384 | ok |
| sha512 | ok |
| sha3_256 | ok |
| blake2b | ok |
| blake2s | ok |
| blake3 | ABSENT (`ValueError: Unknown hashing algorithm`) |
| `hmac.new(b"k", b"msg", "sha256")` | ok (correct digest) |

All present digests matched hardcoded official test vectors — the
implementations are correct, not just present. **No symmetric AEAD exists
anywhere** (no AES-GCM, no ChaCha20-Poly1305): stdlib has none and
pyca/cryptography cannot build (no `_ctypes`/cffi). AEAD requires a Rust
component or the management canister (vetKD, when available).

# Kybra 0.7.1 system-API inventory

Source audited: `venv/lib/python3.10/site-packages/kybra/` (`__init__.py`,
`canisters/management/{basic,http,tecdsa,bitcoin}.py`).

Two calling styles:

1. **Synchronous `ic.*` statics** — plain calls, usable in queries/updates.
2. **Management-canister service methods** — async pattern, update-only:
   `result: CallResult[T] = yield management_canister.method(args)` then
   `match(result, {"Ok": ..., "Err": ...})`; attach cycles with
   `.with_cycles(n)` / `.with_cycles128(n)`.

| Capability | Exact API | Notes |
|---|---|---|
| Randomness | `management_canister.raw_rand() -> blob` | Async/update-only. 32 bytes. The ONLY entropy source |
| Time | `ic.time() -> nat64` | ns since epoch, consensus time |
| tECDSA | `management_canister.ecdsa_public_key(EcdsaPublicKeyArgs) -> EcdsaPublicKeyResult`; `management_canister.sign_with_ecdsa(SignWithEcdsaArgs) -> SignWithEcdsaResult` | `EcdsaCurve` variant has **only `secp256k1`**. Args: `{message_hash: blob, derivation_path: Vec[blob], key_id: {curve, name}}`. Needs cycles on mainnet |
| **Schnorr** | **ABSENT** | `sign_with_schnorr` / `schnorr_public_key` do not exist anywhere in the 0.7.1 package (verified by full-source grep). 0.7.1 predates the Schnorr management-canister API. **PYRE Phase 3 blocker** — workarounds: hand-rolled call via `ic.call_raw(Principal.from_str("aaaaa-aa"), "sign_with_schnorr", ic.candid_encode(...), cycles)`, or a custom `Service` subclass declaring the method |
| Performance | `ic.performance_counter(counter_type: nat32) -> nat64` | |
| Cycles balance | `ic.canister_balance() -> nat64`, `ic.canister_balance128() -> nat` | Plus `msg_cycles_accept/available/refunded` (+128 variants) |
| Certified data | `ic.set_certified_data(data: blob)`, `ic.data_certificate() -> Opt[blob]` | |
| Stable memory (raw) | `ic.stable_grow/read/write/size/bytes` (nat32) and `ic.stable64_grow/read/write/size` (nat64) | |
| Stable structures | `StableBTreeMap[K, V](memory_id: nat8, max_key_size, max_value_size)` — `.get/.insert/.remove/.contains_key/.is_empty/.items/.keys/.values/.len` | Must be declared statically in the canister's main module |
| Timers | `ic.set_timer(delay: Duration, func) -> TimerId`, `ic.set_timer_interval(interval, func) -> TimerId`, `ic.clear_timer(id)` | Plus `@heartbeat` decorator |
| HTTPS outcalls | `management_canister.http_request(HttpRequestArgs)` | `HttpRequestArgs = {url, max_response_bytes: Opt[nat64], method: {get/head/post}, headers, body: Opt[blob], transform: Opt[HttpTransform]}`; transform is `{function: (Principal, str), context: blob}` naming a local `@query`. Requires `.with_cycles(n)` |
| Inter-canister | `ic.call_raw / call_raw128 / notify_raw`, `ic.candid_encode / candid_decode`, `Service` + `@service_query/@service_update` | |
| Identity/msg | `ic.caller() -> Principal`, `ic.id() -> Principal`, `ic.method_name()`, `ic.arg_data_raw()`, `ic.accept_message()`, `ic.reject/reply(...)`, `ic.trap(msg)` | |
| Lifecycle | `@init`, `@pre_upgrade`, `@post_upgrade`, `@inspect_message`, `@heartbeat`, guards (`guard=` on `@query/@update`) | `@init`/`@post_upgrade` need explicit `-> void` |
| Bitcoin API | `bitcoin_get_balance/get_current_fee_percentiles/get_utxos/send_transaction` | Present in management canister bindings |
| Canister mgmt | `create_canister, update_settings, install_code, uninstall_code, start/stop_canister, canister_status, delete_canister, deposit_cycles, provisional_*` | |
