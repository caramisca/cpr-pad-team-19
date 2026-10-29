# Laboratory 3 integration and release runbook

This runbook covers Mihai's delivery and its dependencies. Passing the scoped smoke test does
not demonstrate the full team's SSE, WebSocket, notification and physical-instance eviction tasks.

## Integration state and release order

Status checked on 29 October 2026. The feature PRs listed below are already merged into their
repositories' `dev` branches; they must not be reimplemented or described as pending reviews.

| Repository | Integrated work | Remaining release step |
|---|---|---|
| Service Discovery | #5 status/logs, #6 Docker/CI, #7 monitoring circuits, #3 notifications | Review [confirmation fix #8](https://github.com/DariaRateeva/service-discovery/pull/8); configure DockerHub push credentials; [draft release #9](https://github.com/DariaRateeva/service-discovery/pull/9) |
| Gateway | #12 discovery, #13 protection definitions, #14 publication, #15 circuits, #16 instance removal, #17 log IDs | Reviewed `dev -> main` release and public image |
| Applicant | #9 feature, #10 release | Released at `5c9b4c0`; public `0.4.0` verified |
| Credential | #10 feature, #11 release | Released at `55b3d3c`; public `0.4.0` verified |
| CPR | #197 Compose/smoke, #198 workflow, #199 private release pointers, #200 Postman | Refresh common-service pointers after their actual releases; publication gate and final E2E |

CPR `dev` currently pins old SD `cf1b13f` and Gateway `b5c58fc`. A recursive checkout of those
pointers misses the integrated status, notification and G7/G10 changes. The final pointer update
must reference the published release commits, whose hashes do not exist yet. The public image
name in Compose alone neither updates source pointers nor proves publication.

The common repositories require an approval by another teammate, conversation resolution,
feature PRs into `dev`, and a reviewed release PR `dev -> main`. Features normally squash into
`dev`; milestone releases use merge commits. Do not bypass protections. Rulesets for both common
repositories' `dev` and `main` were verified active. Individual Applicant/Credential repositories
follow the documented owner-merge exception because classmates cannot be collaborators there.

The SD workflow publishes only on a push to `main`. No SD repository secrets were configured at
the check: `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` must permit pushing to the configured
`caramisca/service-discovery` namespace. Configure them through GitHub's secret settings; do not
copy a developer's unrelated broad Docker credentials into a common repository. A successful PR
build does not publish an image. Gateway already has its DockerHub secret names configured.

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

At the 28 October publication audit, six application images passed the public version,
architecture and matching-latest checks. SD, Gateway, Player and Session `0.4.0` returned 404.
Re-run the gate for the current state before a release; a local PR image is never publication proof.

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

Moderation, Rules and Record now have two replicas configured. DMS has one public WebSocket
instance and one internal replica sharing Redis. Player and Session still need their owners'
discovery/replica configuration. Verify that each Java replica registers a physical address rather
than its shared `SERVICE_URL`, and demonstrate SSE/WS/event behavior across replicas.

The common [SD contract](SERVICE_DISCOVERY_CONTRACT.md) records registration, status, monitoring,
notifications and physical-instance removal. The monitor confirmation fix keeps three health
failures inside the task-timeout-times-3.5 window even when normal polling is every ten seconds.

## Scoped container smoke test

```powershell
python scripts/lab3_smoke.py
# Or explicitly test local common-service builds under separate tags:
python scripts/lab3_smoke.py --sd-image caramisca/service-discovery:lab3-monitor-check-20261029 --gateway-image diana7376/gateway-service:lab3-dev-check-20261029 --output docs/evidence/lab3-mihai-smoke-2026-10-29.json
# Include published University Record with its actual PostgreSQL database:
python scripts/lab3_smoke.py --real-registry --sd-image caramisca/service-discovery:lab3-monitor-check-20261029 --gateway-image diana7376/gateway-service:lab3-dev-check-20261029 --output docs/evidence/lab3-mihai-real-registry-smoke-2026-10-29.json
```

Requires local `0.4.0` images. It derives a subset of the proposed root Compose, starts a unique
project/network/volumes, binds only Gateway to localhost port 18080, and deletes only its own
temporary project resources. Use `--port` if 18080 is occupied. It uses explicit fixture credentials,
separate test databases and, by default, a mock university-record dependency inside Credential.
`--real-registry` instead starts the published University Record and its PostgreSQL, verifies a
real student lookup and issues a credential from the demo data. Notifications use a private local
Discord-webhook fixture; no messages are sent to developers or Discord. The test does not build
images or bypass the image-only Compose rule.

Verified locally with the combined SD/Gateway PR images and Mihai's service changes:

- Two healthy, distinct instances of each service with version/instance/load status.
- Real Applicant → Gateway → Credential calls and shared Redis reads from both replicas.
- Round-robin routing, cross-service request IDs and visible instance IDs in logs.
- Public API-key rejection/acceptance; business service health ports remain private.
- Dynamic Applicant scale 2 → 3 → 2 and graceful deregistration.
- SD restart followed by heartbeat 404 and re-registration of all four replicas.
- Three failures from a controlled physical-instance fixture cause Gateway to deregister it from
  SD and stop routing to it, while both healthy replicas keep serving (G10). The fixture health
  stays healthy, and its heartbeat is renewed: this proves business eviction rather than TTL expiry.
- Real failed dependency calls open the Applicant circuit; restarting Credential and passing
  the recovery window restores successful generation.

The smoke run emits a result JSON path in the OS temporary directory; `--output` also writes a
chosen evidence file. It records whether the registry was real or mocked, plus image references
and IDs. Its common-service images can be local PR builds, so this evidence is separate from
public-image verification and the final full-team stack.

On 29 October both scoped runs passed, including G10, and the real-registry run also verified
HTTP critical-load notification delivery to the local fixture. Its University Record SD snapshot
contained no registered instances despite two healthy running containers. Dependency requests
succeeded through Gateway's static fallback; this does not demonstrate discovery/load balancing
for that Java service. Its owner must verify the published image and registration configuration.

## Remaining checks for the complete laboratory

- Peer review and merge of the new SD confirmation fix, then the common-service releases and CPR
  source-pointer update. Code review approval must come from another teammate.
- Public `0.4.0` images for every service; successful publication gate before CPR release.
- Real-channel critical-load alert receipt with credentials kept local. The current local `.env`
  has neither notification channel configured, so fixture tests cannot certify real delivery.
- Player/Session lifecycle, replicas and outbound circuits; per-instance Java registration;
  full-team state/event consistency and SSE/WS regressions across replicas.
- Full-team E2E and University Record registration. The real-registry smoke verifies Applicant,
  Credential and PostgreSQL-backed University Record calls, but observed no SD entries for that
  dependency; static fallback is not a substitute for its G5 registration/round-robin demonstration.
- Required coverage, clean staged diffs, substantive contributions and genuine peer reviews.
- Teams slot/deadline and a working demonstration on the presenting laptop.

The dated JSON evidence records the image references and actual local image IDs used. Local
common-service tags are PR builds, not published release artifacts. A scoped pass is separate from
final image publication and the full-team demonstration.

Local Postman collections can contain private environment values. Do not stage them wholesale;
published collections must have empty keys and take credentials from a local environment.
