# Platform compatibility

Elastic Web Platform 1.x describes what this process can orchestrate:

- meta-schema `>=1.0,<2.0`
- execution contract `>=1.0,<2.0`
- recipe model `>=1.0,<2.0`
- tool calling `>=1.0,<2.0`

Current constant: `PLATFORM_VERSION = 1.0.0` in `packages/federation/elastic_platform.py`.

A capability package declares its own version and the contract range it needs. Shipping capability 3.4 does not require platform 3.4. A meta-schema 2.0 document is `PLATFORM_INCOMPATIBLE` until this platform's range includes it.

Device and OS compatibility are not platform compatibility. Those are VDX facts on the projection (`SUPPORTED`, `os_unsupported`, `unsupported_reason`). Elastic Web reports them. It does not invent them.

Different OS versions must be allowed to produce different profiles. The negotiator does not treat "Android" as sufficient. `SUPPORTED=false` with a reason stops execution before the tool is called.
