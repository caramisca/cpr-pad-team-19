# Lab 4: livrarea lui Mihai / caramisca, 11 noiembrie 2026

## Starea actuala

Partea implementata de Mihai este livrata in serviciile proprii si pregatita pentru integrarea
CPR prin PR cu peer review. Laboratorul complet al echipei ramane in integrare; vezi
[planul de finalizare si prezentare](LAB_4_PRESENTATION_READINESS.md).

Repartizarea a fost reverificata din **ambele screenshoturi originale ale Dariei**, recuperate
impreuna cu conversatia Telegram din 3-9 noiembrie. Randul **Mihai** iti apartine; randul **You**
este al Dariei, autoarea tabelului. PDF-ul Lab 4 defineste cerintele, iar al doilea screenshot
adauga obligatiile fiecaruia in cele doua servicii proprii.

## PR-uri si release-uri verificate

| Livrabil | PR / stare |
|---|---|
| Contract, documentatie, Prometheus initial | [CPR #271](https://github.com/caramisca/cpr-pad-team-19/pull/271), merged in dev |
| Broker topics / gRPC | [Broker #6](https://github.com/DariaRateeva/message-broker/pull/6), merged in dev |
| Applicant Lab 4 + corectia JSON | [#11](https://github.com/caramisca/applicant-service/pull/11) si [#13](https://github.com/caramisca/applicant-service/pull/13), merged in dev |
| Credential Lab 4 + corectia JSON | [#12](https://github.com/caramisca/credential-service/pull/12) si [#14](https://github.com/caramisca/credential-service/pull/14), merged in dev |
| Applicant dev -> main | [release #12](https://github.com/caramisca/applicant-service/pull/12), merged prin merge commit |
| Credential dev -> main | [release #13](https://github.com/caramisca/credential-service/pull/13), merged prin merge commit |
| CPR: partea proprie de release/monitoring | Ramura `chore/cpr/lab4-mihai-release`, PR separat cu peer approval obligatoriu |

| Imagine publica | Commit main si tag Git |
|---|---|
| `caramisca/applicant-service:0.5.0` | `341e8c36e10830a83ff2fe5596ce8b493b35edf2`, `v0.5.0` |
| `caramisca/credential-service:0.5.0` | `a05ba8bd8e5103de4d3efd343cf8254b59c0bb79`, `v0.5.0` |

Pentru ambele imagini s-au verificat accesul public, manifestele **linux/amd64 + linux/arm64** si
`latest` cu acelasi digest ca `0.5.0`. Dovezile cu digesturile si CI-ul exact sunt in
[release evidence](evidence/lab4-mihai-release-2026-11-11.json). Gitlink-urile CPR sunt pregatite
la aceste commituri finale main, dupa publicare, impreuna cu tagurile Compose si IMAGES din checker.

Base Compose poate rula noile imagini in modul Http existent. Activarea Lab 4 a serviciilor
proprii este pregatita separat in `docker-compose.lab4-mihai.yml`; aplicati overlay-ul numai
cand brokerul si adaptorul real University Record sunt integrate de colegi. Un overlay valid
sintactic nu demonstreaza existenta acelor componente.

## Ce am implementat

| Partea ta | Livrabil |
|---|---|
| CPR: envelope, topic names, `.proto` | Contract v1, schema comuna si copii identice in cele trei implementari |
| Broker G6b | Fan-out catre serviciile abonate din SD, o coada/copie per serviciu logic, leasing, FIFO, confirmare dupa COMMITTED |
| Broker G7b | HTTP `GET /topics` si gRPC `ListTopics`, bazate pe abonamentele live din SD |
| Broker G8a | gRPC Call/Publish/Deliver, deadline si request ID, cate un thread nou per RPC, puncte de integrare pentru Diana/Andi |
| CPR G3a | README actualizat, diagrama Mermaid, documentatie de integrare si status explicit |
| CPR G10c | Prometheus, descoperirea tuturor replicilor, trei reguli de alerta si query-uri pentru Grafana Dianei |
| Applicant + Credential G3/G4 | Sectiuni README, doua colectii Postman, `/internal/logs` NDJSON pentru colectorul lui Andi |
| Applicant + Credential G5/G8 | Mod `Grpc`: apelurile de business trec prin broker; serverele gRPC invoca direct handler-ele existente |
| Applicant + Credential G6 | Abonamente SD si evenimente reale: session.closed -> applicant.deleted -> credential cleanup |
| Applicant + Credential G9 | Redis outbox atomic cu create/delete, inbox comun replicilor, cleanup idempotent, COMMITTED/RETRY/REJECTED distincte |
| Applicant + Credential G10 | Contoare requests/errors, durata cumulata si active requests la `/metrics` |

Cele doua servicii au release **0.5.0** publicat si tag Git **v0.5.0**, cu CI de publicare verificat.
Nu suprascriu release-ul 0.4.0. Comportamentul Lab 4 se activeaza explicit prin
`Messaging__Enabled=true`, `Messaging__BrokerUrl` si modul dependentei `Grpc`.
Niciun `/internal/mock-events` nu exista in cele doua servicii ale tale; adaptoarele vechi ale
celorlalti autori se retrag in PR-urile lor.

Detaliile API si punctele concrete de integrare sunt in
[MESSAGE_BROKER_CONTRACT.md](MESSAGE_BROKER_CONTRACT.md).

## Corectia de integrare din 11 noiembrie

Ambele `Messaging/ServiceRpc.cs` pastreaza acum `Content-Type` in ServiceReply, pe langa status,
JSON, Location, X-Request-Id si X-Instance-Id. Testele compara raspunsuri REST/gRPC 200/400/404
si verifica filtrarea cu date pentru doua sesiuni/proprietari diferiti. Gateway trebuie sa
transmita query string-ul integral in path; aceasta corectie in Gateway ramane la Diana.

Cele doua colectii Postman includ `runLab4GatewayChecks=false`, implicit. Pe stack-ul comun
final setati variabila la `true` pentru verificari suplimentare de Content-Type si query filters.
Diagnosticele private raman separat opt-in (`runInternalDiagnostics=false`); porturile interne
nu se expun public pentru a rula colectiile.

Prometheus are acum joburi pentru toate cele opt servicii de domeniu, broker si el insusi,
inclusiv ambele nume Compose DMS. Interfetele asteptate de la ceilalti autori sunt documentate in
[monitoring/README.md](../monitoring/README.md). `check_lab4_monitoring.py --scope team` detecteaza
si joburile DNS fara nicio tinta; `up == 0` singur nu surprinde aceasta situatie.

## Dovezi actuale

- **Applicant: 112 teste, 0 skipped, coverage 90.07%.**
- **Credential: 135 teste, 0 skipped, coverage 90.75%.**
- Testele Release au rulat pe .NET 8, cu Redis real; pragul CI 80% a trecut.
- CI de feature, dev, main si publicare: verde pentru commiturile livrate.
- **59 scripturi Postman** din cele doua colectii au sintaxa JavaScript valida.
- `promtool`: configuratie valida si toate cele **5 reguli** valide.
- CPR: **6 teste trecute**, configuratiile Compose base/overlay/monitoring valide si
  `check_lab3_release.py --require-published` reusit pentru toate cele zece imagini pin-uite.
  Acest checker nu include inca brokerul si nu probeaza activarea Lab 4 a tuturor serviciilor.
- [Smoke nativ actual](evidence/lab4-mihai-smoke-2026-11-11.json): doua replici per serviciu,
  gRPC/HTTP2 prin broker, filtre/headere JSON, Redis comun, topic cleanup, inbox comun, restart
  serviciu si recuperare outbox. **University Record este fixture explicit; Gateway este absent.**
- [Smoke imagini publice](evidence/lab4-mihai-public-containers-2026-11-11.json): gRPC intre
  containere Linux cu imaginile Applicant/Credential 0.5.0 descarcate public, filtre/headere,
  citire din ambele replici Credential si cleanup dupa commit. Broker/SD sunt builduri locale
  pentru test; nu sunt prezentate ca release-uri ale colegilor.
- [Monitoring actual](evidence/lab4-mihai-monitoring-2026-11-11.json): sase targeturi UP,
  doua Applicant, doua Credential, broker si Prometheus. Nu sunt toate serviciile echipei.
- [Rezumat teste](evidence/lab4-mihai-tests-2026-11-11.json): numere extrase din TRX/Cobertura.

Dovezile din 9 noiembrie sunt pastrate ca istoric. Auditul dinaintea interventiei este separat
in [LAB_4_AUDIT_2026-11-11.md](LAB_4_AUDIT_2026-11-11.md); statusul actual este cel din acest raport.

## Ce mai trebuie echipei

1. **Review CPR pentru aceasta livrare.** README cere aprobarea altui coleg pentru contracte,
   submodule si repository-uri comune. PR-ul nu se integreaza automat si nu ocoleste protectiile.
2. **Diana:** request/reply queues reale, query string si dependente gRPC/protobuf corecte in
   Gateway, teste actualizate, alimentarea load cache-ului si rerutare impreuna cu Andi; adaptoarele
   reale Rules/Record si panouri Grafana pentru toate serviciile, inclusiv contoarele C#.
3. **Andi:** circuit breaker real in broker, store durabil, DLC si endpoint de listare, endpoint
   Gateway pentru download loguri; integrarea propriilor servicii.
4. **Daria:** integrarea brokerului/SD si a tuturor release-urilor in Compose, release check/runbook
   Lab 4, adaptoarele si release-urile Player/Session.
5. **Fiecare autor:** imagini publice reale si proba comuna cu serviciile proprii, ACK dupa commit,
   loguri/metrici si contract protobuf compatibil.
6. **Impreuna:** flux Gateway -> broker queues -> Applicant -> Credential -> University Record
   real; probe de topic cleanup, persistenta broker/DLC, circuit trip/reroute si load balancing;
   toate targeturile/panourile prezente. Apoi release-ul CPR prin PR dev -> main.

**Limita G9:** store-ul brokerului verificat este in memorie. Outbox/inbox durabile la servicii
nu garanteaza recuperarea unui eveniment deja acceptat de broker dupa restartul brokerului.
Nu se declara fiabilitate end-to-end pana la integrarea si verificarea store-ului lui Andi.

## Repetarea probei proprii

Pastrati checkouts `broker`, `applicant`, `credential`, `discovery` in acelasi workspace;
compilati cele doua servicii in Release. Sunt necesare .NET 8, dependentele Python din
`scripts/requirements-lab4-smoke.txt` si Redis separat pentru test (implicit localhost:16394).

```powershell
python scripts/lab4_mihai_smoke.py --workspace <workspace> --dotnet <dotnet8-runtime> --evidence <evidence.json>
python scripts/check_lab4_monitoring.py --scope owned --evidence <monitoring.json>
```

Scriptul nativ porneste numai procesele lui, foloseste prefix Redis unic si le curata la final.
Proba containerelor ruleaza `scripts/lab4_container_probe.py` in brokerul proiectului de test.
Pentru acceptarea finala a echipei folositi **--scope team**, nu owned, si checklistul de prezentare.

Modificarile Lab 3 existente in directorul principal au fost pastrate. Lucrul Lab 4 este in
checkout-urile izolate `.local/lab4-mihai`; nicio implementare privata a colegilor nu a fost
inlocuita sau declarata completa prin fixture.
