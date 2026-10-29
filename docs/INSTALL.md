# Installation owner: package.json and scripts/prepare-runtime.py

This release is an unofficial port of the pinned 6.x companion family. It does not upgrade an existing deployment automatically. Keep your live configuration and memory outside these repositories.

0. This preview currently requires the Cortico 0.2.8 compatibility patch shipped in the memory repository. On a clean TEST checkout, run `git apply --check <memory-repository>/patches/cortico-0.2.8-compat.patch`, inspect it, then apply it with `git apply`. The patch adds provider routing, cancellable fork operations, deferred-event trigger control and pause callbacks. Do not blindly apply it to another customized Core. It is not an upstream-official patch.

1. Download the four tagged source archives, or clone the four repositories linked in the README. In a Cortico 0.2.8 checkout, keep them outside your production deployment. The memory package is a Bot extension; the other three are World extensions. Do not start a second memory Bot alongside an existing Bot against the same database.
2. In Cortico WebUI, open Extensions, choose manual installation and select each checkout's absolute directory path. Follow Cortico's dependency/build approval instructions and restart the test instance. From the Cortico repository, `pnpm check:extension <path>` checks package contracts. Use matching private-companion package versions. The process-wide registry is scoped by deployment directory and tolerates separately resolved copies of that same version. GitHub dependencies are declared; npm registry publication is not required. For an offline install, link the local private-companion package into each package manager workspace instead.
3. With Python 3.12+, run from the memory repository:

```sh
python scripts/prepare-runtime.py --companion ../Cortico-Private-Companion --content ../Cortico-Content-Companion --memewiki ../Cortico-MemeWiki
```

The script validates all selected source directories, refuses an existing output directory, copies only source code into `.runtime/sources`, and creates `.runtime/python` with the bundled AstrBot SDK's declared dependencies. It does not write deployment settings. It needs package-index access to install Python dependencies. `--sources-only` is available for an existing compatible environment; that option does not prove dependencies are installed. `--output` can place the runtime outside the checkout. Do not commit the runtime directory.

4. Start with a new **test deployment** using `cortico-bot-memory-companion`. Copy the printed `astrbotCompanion` configuration into that deployment; set `enabled: true` only when ready. Enable World ids `private-companion`, `content-companion`, and `memewiki` as required. The setup output has `enabled: false` intentionally. Do not copy the production configuration or database into a public repository.
5. Configure providers through Cortico, then select their actual Provider IDs on the original plugin model pages. No API key, real contact, default personality, voice model or existing memory is shipped. Local embedding is optional: install/configure a compatible fastembed backend separately before enabling it. The default does not download an embedding model.
6. Original pages bind only to 127.0.0.1:7790, require an authenticated Cortico launch link, and expire sessions. Do not publish launch URLs or expose the port through a tunnel.

QQ support requires a QQ World providing the internal `qq_companion_transport` contract, plus ordinary send tools. A regular OneBot connection alone is insufficient. Missing transport actions fail rather than bypassing pause, private/group scope, recall, stream, quiet-hour or Qzone authorization checks. A transport integration reference is in the memory repository's `docs/QQ_TRANSPORT.md`.

When enabling AstrBot life Qzone posts, keep the QQ Qzone transport enabled and set QQ's separate `qzone.chancePerTick` to 0 to avoid competing automatic posting schedules. Only one comment automation should be active. Posts share QQ's daily quota and pause/quiet-hour/stream gates. No setup command publishes a message or Qzone post.

Existing weighted-memory migration is a separate, operator-controlled step. Back up the old deployment and use a copy for acceptance. Do not replace production code or overwrite a memory database as part of an install smoke test.
