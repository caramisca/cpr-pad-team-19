# Laboratory 3 integration and release runbook

This runbook covers Mihai's delivery and its dependencies. Passing the scoped smoke test does
not demonstrate the full team's SSE, WebSocket, notification and physical-instance eviction tasks.

## Integration state and release order

Status checked on 30 October 2026. The feature PRs listed below are already merged into their
repositories' `dev` branches; they must not be reimplemented or described as pending reviews.

| Repository | Integrated work | Remaining release step |
|---|---|---|
| Service Discovery | #5 status/logs, #6 Docker/CI, #7 monitoring circuits, #3 notifications, #8 bounded confirmation, #10 namespace correction | Release [#9](https://github.com/DariaRateeva/service-discovery/pull/9) merged at `c05074d`; main publication and public `drateeva/service-discovery:0.4.0` verified |
| Gateway | #12 discovery, #13 protection definitions, #14 publication, #15 circuits, #16 instance removal, #17 log IDs; #19 excludes upstream 503 from instance failures | Released 0.4.0 at `917726f`, pinned through CPR #221; patch 0.4.1 is prepared in Gateway #20 and its release PR |
| Applicant | #9 feature, #10 release | Released at `5c9b4c0`; public `0.4.0` verified |
| Credential | #10 feature, #11 release | Released at `55b3d3c`; public `0.4.0` verified |
| CPR | #197 Compose/smoke, #198 workflow, #199 private release pointers, #200 Postman, #212 scoped evidence, #213 Java addressing, #215/#216 Player/Session, #217 SD release, #219 per-image versions, #221 Gateway pointer, #222 Rules/Record 0.4.1 | Review patch verification, deliver Gateway 0.4.1 and finalize the reviewed CPR release |

SD is pinned to release `c05074d` and uses `drateeva/service-discovery:0.4.0`. Gateway 0.4.0 is
correctly pinned to `917726f` through CPR #221. Rules and University Record use their published
0.4.1 releases through CPR #222. Each future patch must update image, expected version and source
pointer together; an image name alone neither updates source pointers nor proves publication.

The common repositories require an approval by another teammate, conversation resolution,
feature PRs into `dev`, and a reviewed release PR `dev -> main`. Features normally squash into
`dev`; milestone releases use merge commits. Do not bypass protections. Rulesets for both common
repositories' `dev` and `main` were verified active. Individual Applicant/Credential repositories
follow the documented owner-merge exception because classmates cannot be collaborators there.

The SD workflow publishes only on a push to `main`. Both `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`
repository secret names are now present, and `drateeva/service-discovery` is public. Daria manages
the DockerHub account and token; no token was read or copied into source. Main workflow run
`41053521253` passed tests and publishing on `c05074d`, and both public tags have digest
`sha256:060649dae0429e99c800325caef9c0e4d7693cc658737bff47c9fe08d80cdb67`.
Annotated Git tag `v0.4.0` resolves to `c05074d`. The
[release evidence](evidence/lab3-sd-release-2026-10-30.json) records the source, CI and manifest
checks. A successful PR build alone does not publish an image.

## Version consistency

Each application image has its own pinned `repository:version` in `IMAGES` in
`scripts/check_lab3_release.py`, which must match its Compose image. The current baseline uses
**0.4.0** for most services, with Rules and University Record at **0.4.1**. Independent patches
are supported without changing the other services.
After a patch is published, update only its expected reference, Compose image, release source
pointer and documentation. Missing/unpublished tags fail the gate; there is no version fallback.
Database images retain PostgreSQL/MongoDB/Redis upstream versions; seed jobs use the Redis image
and are not separate application releases. Do not retag old binaries merely to make a check pass.

```powershell
python -m unittest discover -s tests -p test_lab3_release.py
python scripts/check_lab3_release.py
python scripts/check_lab3_release.py --require-published
```

The first configuration check needs Docker Compose CLI but no running engine. It always uses
`.env.example`, never prints resolved environments and checks all image references, private
control-plane ports and the two initial replica counts. The publication check is unauthenticated
against DockerHub: every image must be public, include linux/amd64 and linux/arm64, and have
`latest` pointing at the same manifest digest as its own pinned tag. It fails on missing tags.
Different application images naturally have different digests.

At the 28 October publication audit, six application images passed the public version,
architecture and matching-latest checks. SD, Gateway, Player and Session `0.4.0` returned 404.
On 30 October, after SD release #9, all ten application images passed the public version,
architecture and matching-latest checks using the updated `drateeva/service-discovery` reference.
Re-run the gate before the CPR release; a local PR image is never publication proof.

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

Moderation, Rules and Record have two replicas configured. DMS has one public WebSocket instance
and one internal replica sharing Redis. Player and Session now also have two replicas and
`DISCOVERY_URL` through CPR #216; their release pointers and Session V2 migration arrived in #215.
CPR #213 removed shared `SERVICE_URL` overrides for Rules/Record. Verify physical registration
and SSE/WS/event behavior in the final stack rather than treating configuration as runtime proof.

The common [SD contract](SERVICE_DISCOVERY_CONTRACT.md) records registration, status, monitoring,
notifications and physical-instance removal. The monitor confirmation fix keeps three health
failures inside the task-timeout-times-3.5 window even when normal polling is every ten seconds.

## Scoped container smoke test

```powershell
python scripts/lab3_smoke.py --real-registry
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

Historical evidence: on 29 October both scoped runs passed, including G10, and the real-registry
run also verified HTTP critical-load notification delivery to the local fixture. Its University Record SD snapshot
contained no registered instances despite two healthy running containers. Dependency requests
succeeded through Gateway's static fallback; this does not demonstrate discovery/load balancing
for that Java service. Its owner must verify the published image and registration configuration.

On 30 October the same real-registry smoke passed with the public release images, including
`drateeva/service-discovery:0.4.0` and `diana7376/gateway-service:0.4.0`, after pulling the current
SD, Gateway and University Record images. The
[published-image evidence](evidence/lab3-published-real-registry-smoke-2026-10-30.json) records
all ten scoped checks, including G10, the isolated notification receiver and circuit recovery.
The University Record SD snapshot was again empty at lookup in this smoke's short-TTL setup;
real registry calls succeeded through static fallback. This evidence still does not establish
discovered-instance balancing for that service or full-team SSE/WebSocket behavior. Only this
run's unique temporary Docker project, network and volumes were removed after the test.

On 30 October the full local stack was also tested with Rules/Record 0.4.1. All four reference
replicas reported version 0.4.1 with distinct instance IDs. Restarting only SD recovered all
16 business instances in 14.77 seconds; Rules/Record containers were not restarted. Gateway
GETs for active rules and faculties both returned 200. The
[re-registration evidence](evidence/lab3-rules-record-reregister-2026-10-30.json) records these
checks. The former Rules/Record restart workaround is no longer needed for these patch images.

The G10 fixture now returns 500 for a deliberately failing physical instance. Gateway patch #19
intentionally excludes upstream 503 busy/dependency replies from its failure count, so such a
reply cannot be used as the evidence for G10 removal after that patch.

The updated real-registry smoke uses SD's production-default 30-second TTL and explicitly waits
for two University Record registrations. It asserts both physical registry addresses occur in
Gateway routing logs and that they re-register after SD restart; static fallback no longer counts
as passing that scenario. The
[Gateway 0.4.1 review-image smoke](evidence/lab3-gateway041-review-smoke-2026-10-30.json) passed
all eleven checks with this stricter setup. Its Gateway tag is a local review build, not a claimed
public release. Earlier dated short-TTL evidence remains unchanged.

The [full local-stack summary](evidence/lab3-local-stack-2026-10-30.json) records 23/23 HTTP
contract checks, all 16 domain registrations, SSE and a WebSocket message received by two local
clients. That persistent stack used public Gateway 0.4.0 with Rules/Record 0.4.1. Developer-channel
Discord/Telegram delivery is still separate from the isolated receiver test.

## Remaining checks for the complete laboratory

- Peer review of patch-verification changes, Gateway 0.4.1 publication/integration and the
  reviewed CPR release. SD #8/#10/#9 and CPR #217/#219/#221/#222 are already merged.
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
