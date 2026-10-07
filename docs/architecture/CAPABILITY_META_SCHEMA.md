# Capability meta-schema

Elastic Web understands one meta-schema. The App Store supplies micro-schemas. A new micro-schema does not require an Elastic Web core change.

Meta-schema objects:

- Capability
- Tool
- Input
- Output
- Permission
- Version
- Provider
- ExecutionTarget
- ExecutionProtocol
- Dependency
- Compatibility
- Result
- Error

Micro-schemas are instances: `send_email`, `search_flights`, `book_hotel`, `request_ride`, `open_application`, `create_calendar_event`. They are data. They are not branches in this repository.

Platform version `1.0.0` accepts meta-schema `>=1.0,<2.0` and execution contract `>=1.0,<2.0`. A capability version is not the platform version. Ranges live in `packages/federation/elastic_platform.py`.

The existing `Capability` model in `packages/capability-registry/capability.py` remains the declarative catalog record for retrieval. It is not replaced. Federation evaluates installation, device, and runtime state that the catalog record does not own.

States are not interchangeable:

EXISTS, DISCOVERABLE, INSTALLABLE, INSTALLED, ENABLED, AUTHORIZED, SUPPORTED, EXECUTABLE, AVAILABLE.

Failure codes are not interchangeable. `packages/federation/failure_codes.py` maps each code to retry, request permission, install, select alternative, ask user, degrade, or report impossibility. Nothing maps to a generic error.
