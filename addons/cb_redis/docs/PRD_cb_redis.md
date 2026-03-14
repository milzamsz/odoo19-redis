# Odoo 19 Enterprise Module PRD

## Document Control

- Module Name: `cb_redis`
- Target Platform: `Odoo 19 Enterprise`
- Document Status: `draft`
- Version: `v1.0`
- Date: `2026-03-14`
- Owner: `CB / Redis maintenance`
- Technical Lead: `Odoo platform maintainer`
- Stakeholders: `System administrators, backend developers, operations`

## 1. Executive Summary

### Summary

`cb_redis` is an Odoo 19 Enterprise addon that provides Redis-backed HTTP session storage and Redis Streams background job execution.

It is intended to help:

- system administrators run Odoo in shared or containerized environments
- backend developers move heavy work out of synchronous request handling
- operators monitor queued, running, failed, and retried jobs

For this phase, `cb_redis` stays a single addon. Session and async behavior are hardened in place instead of being split into separate installable modules.

### Why This Matters

The current addon already covers the main concepts, but it is not yet hardened enough for reliable local EE deployment or safe async execution. The biggest gaps are deployment drift, broker gating, retry timing, task execution context, and documentation accuracy.

## 2. Problem Statement

### Current State

- Sessions can be redirected to Redis through `cb_redis`.
- Async work can be queued through `.delayable()` and processed by `worker.py`.
- Local Docker EE deployment is not yet fully wired for this addon.
- Some documented behavior does not match the implemented code.

### Problems to Solve

- Make the addon installable and testable in the local Odoo 19 EE environment.
- Make async behavior safer and more predictable.
- Keep operator and developer documentation aligned with real code.

### Business Impact

- Admins need shared session storage for multi-container deployments.
- Developers need a safe async queue for heavy Odoo work.
- Operators need predictable retry, logging, and recovery behavior.

## 3. Goals

### Business Goals

- Support reliable shared-session Odoo deployments
- Reduce synchronous request load for heavy business operations
- Improve operational confidence in Redis-backed background work

### Product Goals

- Provide a clear admin configuration flow
- Provide a usable `.delayable()` API for backend code
- Provide visible task and channel administration for operators

### Technical Goals

- Harden deployment and validation for Odoo 19 EE
- Enforce broker enablement and safer execution rules
- Keep configuration-derived values consistent at runtime

### Success Metrics

- `cb_redis` installs cleanly in `odoo19_ee_cb_redis_test`
- Session-store and async-broker acceptance scenarios pass
- Documentation and examples match real code paths

## 4. Non-Goals

- Do not merge Redis ORM cache into `cb_redis` in this phase
- Do not split `cb_redis` into separate session and async addons in this phase
- Do not turn `cb_redis` into a generic workflow engine
- Do not redesign business modules that might later call `.delayable()`

## 5. Scope

### In Scope

- Redis session store behavior
- Redis Streams async task dispatch and execution
- Local Docker EE deployment and validation workflow
- Documentation, tests, and admin hardening backlog

### Out of Scope

- Redis ORM cache rollout
- Non-Redis background backends
- Business-module-specific async adapters beyond generic task execution

### MVP Scope

- Installable addon in local EE Docker
- Accurate setup and operator docs
- Clear implementation backlog for broker gating, retry timing, user-context execution, and stream-key correctness
- Keep the current single-addon packaging while improving reliability and safety

### Future Scope

- Redis ORM cache as a separate initiative
- Optional addon split only after the current hardening backlog is complete
- Richer monitoring dashboards or cron-driven retry orchestration if needed

## 6. Assumptions and Constraints

### Assumptions

- Redis 7 is available to the Odoo stack
- Odoo remains on version 19 Enterprise
- `cb_redis` remains a single addon

### Constraints

- Odoo version is exactly `19 Enterprise`
- Local Odoo container is `odoo19-ee`
- Local database container is `odoo19-db`

### Odoo-Specific Constraints

- Session-store patching must stay compatible with Odoo HTTP lifecycle
- View definitions must satisfy Odoo 19 validation rules
- Server-side permission checks must remain explicit for async execution

## 7. Personas and Stakeholders

| Persona | Role | Needs | Success Outcome |
|---|---|---|---|
| Odoo Admin | Configure platform services | Enable Redis safely | Sessions and broker work without manual hacks |
| Backend Developer | Queue heavy methods | Stable async API | `.delayable()` behaves predictably |
| Operator | Monitor and recover tasks | Clear states and logs | Failures are diagnosable and retry behavior is trustworthy |

Key stakeholders:

- Platform engineering
- Odoo customization team
- Operations support

## 8. Business Process Overview

### Current Workflow

1. Admin installs `cb_redis`
2. Admin configures Redis in Settings
3. Developer dispatches async work through `.delayable()`
4. Worker consumes Redis Streams messages and executes tasks

### Target Workflow

1. Admin syncs addon and dependency into the local EE environment
2. Admin configures Redis once through Settings
3. Business code dispatches async work only when broker is enabled
4. Worker executes tasks under the correct user context with real retry timing

### Business Rules

- Session storage must keep filesystem fallback when Redis session storage is disabled
- Async dispatch must be blocked when the broker is disabled
- Operational UI for channels and manual task control must remain admin-focused

## 9. Core Use Cases

### Use Case 1: Configure Redis Session Store

- Actor: Odoo system administrator
- Trigger: Admin wants shared HTTP sessions
- Preconditions: Redis is reachable and `redis` is installed in the container
- Main Flow:
  1. Open General Settings
  2. Configure Redis connection values
  3. Save and verify sessions in Redis
- Expected Result: New sessions are stored in Redis with the configured prefix and TTL

### Use Case 2: Queue an Async Task

- Actor: Backend developer or business flow
- Trigger: A heavy method should not run in the request thread
- Preconditions: Broker is enabled and at least one active channel exists
- Main Flow:
  1. Call `.delayable()` on a recordset
  2. Create `cb.async.task`
  3. Publish the task to the target Redis Stream
- Expected Result: Worker can consume and execute the task

### Edge Cases

- Broker disabled but code still tries to dispatch
- Retry requested with delay but worker does not wait
- Stream prefix changes after channels already exist

## 10. Functional Requirements

### 10.1 Configuration

- FR-001: Admin can configure session-store Redis settings in `res.config.settings`
- FR-002: Admin can configure broker enablement and stream prefix in `res.config.settings`
- FR-003: Connection test gives a clear success or failure message

### 10.2 Business Logic

- FR-010: `.delayable()` can queue public model methods
- FR-011: Worker can consume queued tasks and update task state
- FR-012: Retry policy must be enforceable with real delay semantics

### 10.3 User Interface

- FR-020: Admin can review channels and tasks from the Redis Broker menu
- FR-021: Task form shows payload, state, result, error, and logs
- FR-022: Settings guide the admin toward valid Redis configuration

### 10.4 Security and Permissions

- FR-030: Admin-only UI remains limited to system administrators
- FR-031: Worker execution should run in the requesting user context
- FR-032: Broker-disabled dispatch must fail server-side, not only in the UI

### 10.5 Auditability

- FR-040: Task state changes are visible on the task record
- FR-041: Task log records preserve operational messages

### 10.6 Multi-Company

- FR-050: Redis configuration remains database-scoped
- FR-051: Async task execution must respect normal Odoo access rules

### 10.7 Integration

- FR-060: Redis Session Store integrates with Odoo HTTP session lifecycle
- FR-061: Redis Streams worker integrates with the Odoo registry and database

## 11. Data Model and Configuration Model

### Main Models

| Model | Type | Purpose |
|---|---|---|
| `cb.async.channel` | new | Queue configuration and stream naming |
| `cb.async.task` | new | Async task payload, state, retry, result, and chain metadata |
| `cb.async.task.log` | new | Operational log entries per task |
| `res.config.settings` | existing extension | Redis session and broker configuration |

### Important Fields

| Model | Field | Type | Required | Notes |
|---|---|---|---|---|
| `cb.async.channel` | `code` | Char | yes | Seeded values use `jobs` and `jobs:*` |
| `cb.async.channel` | `stream_key` | Char | computed | Planned as non-stored |
| `cb.async.task` | `state` | Selection | yes | Pending, queued, running, done, failed, cancelled |
| `cb.async.task` | `retry_count` | Integer | yes | Tracks retry attempts |
| `cb.async.task` | `retry_delay` | Integer | yes | Intended retry delay in seconds |
| `cb.async.task` | `requested_by_user_id` | Many2one | planned | Required for safer execution context |
| `cb.async.task` | `date_next_attempt` | Datetime | planned | Required for real delayed retry |

### Relationships

- `cb.async.channel` has many `cb.async.task`
- `cb.async.task` has many `cb.async.task.log`
- `cb.async.task` can chain to `next_task_id`

### Configuration Records

- `ir.config_parameter` values under `cb_redis.*`
- Seeded `cb.async.channel` data records

## 12. UI and UX Requirements

### Target UI Areas

- General Settings
- Async task list and form views
- Channel list and form views

### UX Principles

- Keep configuration close to standard Odoo settings patterns
- Keep operator screens readable and state-driven
- Keep examples aligned with real channel codes and API signatures

### View Requirements

- Settings should explain URL override behavior
- Task view should make failure and retry state obvious
- Search view must stay valid for Odoo 19

### Error Messages

Important errors should be clear and actionable, for example:

- `Redis connection failed: ...`
- `Async broker is disabled. Enable it in Settings before dispatching tasks.`

## 13. Security Model

### Access Rights

- `base.group_system`: full operational access
- business users: no admin UI for channels or manual task management

### Record Rules

- No extra record rules are required for MVP if UI and server-side checks are explicit

### Data Protection

- Store only serialized task arguments and results needed for execution
- Avoid broad privilege escalation in worker execution

### Execution Safety

- Restrict delayed methods to explicit public method names
- Re-check broker enablement server-side
- Execute under the requesting user where practical

## 14. Multi-Company and Multi-Environment Design

### Multi-Company Rules

- Redis configuration is database-wide, not per company
- Task execution must respect normal company access of the executing user
- Session keys must remain scoped by configured prefix and database usage conventions

### Conflict Resolution

- If multiple environments share Redis, distinct prefixes must be configured
- The local EE validation path uses a dedicated disposable database

### Environment Strategy

- Development: local Docker stack with `odoo19-ee`, `odoo19-db`, and `redis`
- UAT: mirror the Redis and worker topology of production
- Production: use the same addon boundary, settings model, and worker contract

## 15. Scalability and Performance Requirements

### Expected Scale

- Companies: low to medium
- Users: tens to low hundreds
- Records per month: depends on business modules using `.delayable()`
- Concurrency pattern: multiple HTTP workers plus one or more async workers

### Performance Goals

- Session access should stay O(1) against Redis
- Async queue operations should not block request handling
- Stream prefix changes should not require manual channel rewrites

### Known Hot Paths

- HTTP session `get` and `save`
- Async task dispatch and worker consume loop

### Performance Risks

- stale stored stream keys after prefix change
- repeated failed tasks without real retry timing

### Mitigation Strategy

- compute stream keys live from current config
- schedule retries explicitly instead of immediate requeue loops

## 16. Technical Architecture

### Module Structure

- `__manifest__.py`
- `redis_session_store.py`
- `async_broker.py`
- `worker.py`
- `models/`
- `views/`
- `security/`
- `data/`
- `docs/`

### Architectural Approach

- Keep Redis session storage and async broker in one addon
- Keep Redis connection settings in `ir.config_parameter`
- Keep worker execution outside the HTTP server

### Extension Strategy

- Monkey-patch `http.Application.session_store`
- Extend `res.config.settings`
- Use model inheritance on `base` to add `.delayable()`

### Odoo 19 Compatibility Notes

- Search-view grouping must use flat filters
- HTTP session patching must stay compatible with current `cached_property` behavior
- Validation and logging should follow Odoo 19 runtime expectations

## 17. Integration Requirements

### Native Odoo Integrations

- `res.config.settings`
- Odoo HTTP session lifecycle
- Odoo registry and ORM for worker execution

### External Integrations

- Redis server reachable over TCP
- Redis Streams support

### Automation

- External worker process consumes messages from Redis Streams
- Future hardening may add time-aware retry dispatch

### Reporting

- Task views and logs provide the main operational reporting surface

## 18. Migration and Upgrade Considerations

### Installation

- Copy addon into mounted custom addons path
- Install `redis` in `odoo19-ee`

### Data Migration

- Seeded channels should remain stable
- Any migration to non-stored `stream_key` must preserve usability of existing channels

### Upgrade Safety

- Avoid breaking existing task states
- Keep docs updated when API signatures or operational behavior change

### Uninstall / Cleanup

- Uninstall should not corrupt unrelated Redis data if prefixes are used correctly
- Session fallback behavior should be documented before removal

## 19. Testing Strategy

### Unit / Model Tests

- dispatch guard when broker disabled
- stream-key computation after prefix changes

### Integration Tests

- session-store configuration and fallback
- async task lifecycle through queue and worker execution

### UI / View Tests

- settings view loads cleanly in Odoo 19
- task and channel views remain valid

### Security Tests

- non-admins cannot use admin operational UI
- worker execution uses the intended user context

### Performance / Volume Tests

- repeated session reads and writes through Redis
- queue behavior under multiple pending tasks

### Acceptance Test Scenario

1. Copy `cb_redis` into mounted addons path
2. Install `redis` in `odoo19-ee`
3. Install `cb_redis` into `odoo19_ee_cb_redis_test`
4. Enable session store and broker
5. Dispatch a test method through `.delayable(channel='jobs')`
6. Run the worker and verify state, logs, and permissions

## 20. Deployment and Validation Plan

### Local Validation

- use the disposable database `odoo19_ee_cb_redis_test`
- tail `/var/log/odoo/cb_redis-test.log` after each install or test cycle

### UAT Validation

- verify the same Redis topology and channel naming strategy
- verify worker deployment commands match the mounted addon path

### Production Readiness Checks

- Redis package installed in runtime image
- addon mounted in custom addons path
- broker gating, retry timing, and user-context execution verified

### Rollback Plan

- disable broker in Settings if async work must be stopped
- disable Redis session store to return to filesystem sessions if needed

## 21. Operational Support

### Logging and Audit

- keep task log entries for dispatch, retry, success, and failure
- keep worker log output readable and correlated to task IDs

### Monitoring

- monitor failed and long-running tasks
- monitor Redis reachability from Odoo and worker containers

### Support Model

- First line: Odoo platform support
- Second line: backend engineering
- Escalation path: platform maintainer

## 22. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Broker enable flag remains UI-only | High | High | Enforce server-side gating in dispatch and worker startup |
| Tasks continue to run as superuser | High | Medium | Add `requested_by_user_id` and execute under that user |
| Prefix changes leave stale stream keys | Medium | High | Make `stream_key` non-stored and compute live |

## 23. Milestones and Delivery Phases

### Phase 1: Discovery and PRD

- confirm environment, references, and current gaps
- publish analysis, PRD, and operator docs

### Phase 2: MVP Hardening

- fix deployment baseline and broker gating
- correct docs and add validation workflow

### Phase 3: Execution Safety

- implement user-context execution
- implement real retry timing

### Phase 4: Hardening and Rollout

- add tests
- run full local validation and close residual risks

## 24. Acceptance Criteria

- AC-001: Admin can install and configure `cb_redis` in the local Odoo 19 EE environment
- AC-002: Session-store and async-broker docs match the real code and environment
- AC-003: Async dispatch is blocked when the broker is disabled
- AC-004: Targeted automated tests and local validation pass for the hardened flow

## 25. Open Questions

- Should delayed retry be worker-driven, cron-driven, or hybrid?
- Which business modules should provide the first end-to-end `.delayable()` reference test?
- Should task argument serialization remain generic JSON only, or gain stricter validation?

## 26. Appendices

### Appendix A: References

- `cb_redis/docs/CB_REDIS_ANALYSIS.md`
- `smile_redis_session_store/redis_session_store.py`
- `open_redis_ormcache/modules/registry.py`

### Appendix B: Example Commands

```powershell
robocopy "C:\Projects\Odoo\odoo-dev\redis\cb_redis" "C:\Projects\Odoo\odoo-instance\v19\ee\addons\custom\cb_redis" /E
python -m compileall "C:\Projects\Odoo\odoo-dev\redis\cb_redis"
docker exec odoo19-ee bash -lc "python3 -m pip install redis"
docker exec odoo19-db bash -lc "PGPASSWORD=odoo_dev_2024 dropdb -h localhost -U odoo --if-exists odoo19_ee_cb_redis_test"
docker exec odoo19-ee bash -lc "rm -f /var/log/odoo/cb_redis-test.log"
docker exec odoo19-ee bash -lc "odoo server -c /etc/odoo/odoo.conf -d odoo19_ee_cb_redis_test -i base,base_setup,cb_redis --without-demo=all --test-enable --test-tags /cb_redis --stop-after-init --no-http --logfile=/var/log/odoo/cb_redis-test.log --log-level=info --log-handler=:INFO"
docker exec odoo19-ee bash -lc "tail -n 200 /var/log/odoo/cb_redis-test.log"
```

### Appendix C: PRD Quality Checklist

- the problem is clear
- scope and non-goals are explicit
- major use cases are documented
- Odoo-specific constraints are acknowledged
- main data model changes are identified
- security and runtime behavior are called out
- testing includes at least one end-to-end scenario
