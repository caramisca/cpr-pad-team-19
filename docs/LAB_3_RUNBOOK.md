# Laboratory 3 integration and release runbook

This runbook covers Mihai's delivery and its dependencies. Passing the scoped smoke test does
not demonstrate the full team's SSE, WebSocket, notification and physical-instance eviction tasks.

## Review and release order

| Repository | Reviewable change | Dependency |
|---|---|---|
| Service Discovery | [#5: status/logs](https://github.com/DariaRateeva/service-discovery/pull/5) | Current registry/polling API |
| Service Discovery | [#6: Docker and tested publishing](https://github.com/DariaRateeva/service-discovery/pull/6) | Owner configures DockerHub secrets and public repository |
| Service Discovery | [#7: monitoring circuits and notifier handoff](https://github.com/DariaRateeva/service-discovery/pull/7) | Status timeout from #5; notifier implementation from Andi #3 |
| Gateway | [#12: discovery integration](https://github.com/diana7376/gateway-service/pull/12) | Existing SD API; preserves hooks for Andi |
| Gateway | [#13: branch protections](https://github.com/diana7376/gateway-service/pull/13) | Owner/admin applies the script; merging JSON alone is insufficient |
| Gateway | [#14: 0.4.0 publication preparation](https://github.com/diana7376/gateway-service/pull/14) | Feature integration and reviewed `dev → main` release |
| Applicant | [#9 feature](https://github.com/caramisca/applicant-service/pull/9), [#10 release](https://github.com/caramisca/applicant-service/pull/10) | Merged; v0.4.0 and public multi-platform image verified |
| Credential | [#10 feature](https://github.com/caramisca/credential-service/pull/10), [#11 release](https://github.com/caramisca/credential-service/pull/11) | Merged; v0.4.0 and public multi-platform image verified |
| CPR | [#197: Compose, smoke and release checks](https://github.com/caramisca/cpr-pad-team-19/pull/197) | Draft until required public images and release pointers are verified |
| CPR | [#198: workflow clarification](https://github.com/caramisca/cpr-pad-team-19/pull/198) | Peer approval |
| CPR | [#199: actual private-service release pointers](https://github.com/caramisca/cpr-pad-team-19/pull/199) | Public images/manifests verified; peer approval |
| CPR | [#200: all eight Gateway-health Postman checks](https://github.com/caramisca/cpr-pad-team-19/pull/200) | Gateway 0.4.0 release; 8 requests / 64 assertions passed |

The common repositories require an approval by another teammate, conversation resolution,
feature PRs into `dev`, and a reviewed release PR `dev → main`. Features normally squash into
`dev`; milestone releases use merge commits. No direct protected-branch pushes or bypass merges.
Individual Applicant/Credential repositories follow the explicit owner-merge exception in the
CPR README because classmates must not be added as collaborators there.

All three SD changes were tested together (73 tests passed) on a local validation branch; that branch
is not a substitute for peer approval or an integration-branch merge. The same applies to the
Gateway discovery/version combination used for the smoke test.

## When Diana can continue

The required code and reproducible smoke test are available for review. Diana's previously merged
round-robin and monitoring work can be validated against it. The shared stack is ready for her
without local source access to private services only after:

1. SD #5/#6/#7 and Gateway #12/#14 are reviewed and merged into `dev`.
2. SD has a public DockerHub repository and CI credentials with push permission for the configured
   namespace (`caramisca/service-discovery` in this delivery).
3. Reviewed common-service releases publish `0.4.0`, and the other application owners publish
   their own `0.4.0` releases.
4. The publication gate succeeds and the CPR draft is completed with release submodule pointers.

An owner must also apply Gateway #13: the current collaborator has WRITE, not ADMIN. This is a
GitHub permission constraint; the rule definitions are already concrete and reviewable.

## Version consistency

All ten application images in the proposed Compose release are fixed at **0.4.0**. Database
images retain PostgreSQL/MongoDB/Redis upstream versions; seed jobs use the Redis image and
are not separate application releases. Do not retag old application binaries as `0.4.0` merely
to make a version check pass.

```powershell
python -m unittest discover -s tests -p test_lab3_release.py
python scripts/check_lab3_release.py
python scripts/check_lab3_release.py --require-published
```

The first configuration check needs Docker Compose CLI but no running engine. It always uses
`.env.example`, never prints resolved environments and checks all image references, private
control-plane ports and the two initial replica counts. The publication check is unauthenticated
against DockerHub: every image must be public, include linux/amd64 and linux/arm64, and have
`latest` pointing at the same manifest digest as its own `0.4.0` tag. It fails on missing tags.
Different application images naturally have different digests.

At the initial 27 October audit, the nine pre-existing images had public `0.3.0` tags, no public
`0.4.0` tags were found, and SD had not been published. This is a dated observation, not current
release proof; rerun the gate after the owners' publishing workflows finish.

Later in the same session, Applicant and Credential were released through their own feature and
milestone PRs. Their public `0.4.0` tags, amd64/arm64 platforms and matching `latest` digests were
verified, with Git release tags fixed to the main merge commits. CPR #199 records the manifests
and release pointers. The remaining eight application images still require their owners' release
steps; a locally built common-service image is not counted as public publication.

## Running the release stack

Prepare `.env` locally from `.env.example`, configure real values, then:

```powershell
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --since 5m gateway-service service-discovery
docker compose up -d --scale applicant-service=3 --scale credential-service=3
```

Default Applicant/Credential replicas are two. Each registers its actual container address,
heartbeats at the interval returned by SD, re-registers after an unknown heartbeat and sends a
best-effort deregistration on graceful shutdown. Separate per-service Redis stores are shared
between replicas; seed jobs and persistent volumes remain. No `container_name` or fixed host
port is assigned to these replicas.

SD is single-process because its registry is in memory. Its 8089 port and Gateway internal 8090
are private. SD's own health does not depend on business services. Gateway polls every five
seconds in this Compose stack and keeps the last valid snapshots on a temporary SD failure.

Other owners' services are not blindly scaled. Before increasing their replica count, verify
registration, shared state, event delivery and the public connection contract. DMS's fixed
8088 host mapping and negotiated WebSocket address need an owner-provided scaling solution.

## Scoped container smoke test

```powershell
python scripts/lab3_smoke.py
```

Requires local `0.4.0` images. It derives a subset of the proposed root Compose, starts a unique
project/network/volumes, binds only Gateway to localhost port 18080, and deletes only its own
temporary project resources. Use `--port` if 18080 is occupied. It uses explicit fixture credentials,
separate test databases and the mock university-record dependency inside Credential; no messages
are sent to developers or Discord. It does not build images or bypass the image-only Compose rule.

Verified locally with the combined SD/Gateway PR images and Mihai's service changes:

- Two healthy, distinct instances of each service with version/instance/load status.
- Real Applicant → Gateway → Credential calls and shared Redis reads from both replicas.
- Round-robin routing, cross-service request IDs and visible instance IDs in logs.
- Public API-key rejection/acceptance; business service health ports remain private.
- Dynamic Applicant scale 2 → 3 → 2 and graceful deregistration.
- SD restart followed by heartbeat 404 and re-registration of all four replicas.
- Real failed dependency calls open the Applicant circuit; restarting Credential and passing
  the recovery window restores successful generation.

The smoke run emits a result JSON path in the OS temporary directory. Its university registry
is mocked, and its images can be local PR builds, so this evidence is separate from public-image
verification and the final full-team stack.

## Remaining checks for the complete laboratory

- Shared contract/status documentation coordinated with Daria; mirror individual contracts.
- Andi's Gateway G7/G10 failure counting, physical removal, quarantine and half-open recovery;
  discovery hooks alone do not implement these tasks.
- SD polling-to-notifier connection after the notification PR is rebased onto Diana's poller,
  including real-channel alert receipt with credentials kept local/secret.
- Merge SD #7 for outbound monitor circuit protection and the poller/notifier handoff; it was
  verified together with #5/#6. Physical-instance business-routing eviction remains Gateway work.
- Other owners' lifecycle/state changes, outbox/event consistency, shared rate limits and
  SSE/WS behavior across their replicas, followed by real full-team E2E.
- ≥80% required coverage, clean staged diffs, current image manifests and release pointers,
  substantive common-service contributions and genuine peer reviews.
- Teams presentation slot/deadline and a working demonstration on the presenting laptop.

Local Postman collections can contain private environment values. Do not stage them wholesale;
published collections must have empty keys and take credentials from a local environment.
