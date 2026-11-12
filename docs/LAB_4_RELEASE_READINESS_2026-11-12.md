# Lab 4 — verificare finală, gitlink-uri și restanțe

Verificare din 12 noiembrie 2026, după CPR #290–#292 și Broker #11. Acest raport înlocuiește
concluziile snapshot-urilor anterioare. Cerințele sunt cele din `PAD_LAB_4_V1.pdf` și sunt cumulative.

**Decizie: NU încă release complet / promovare CPR pe main.** Fluxurile principale funcționează,
dar rămân 28 de aserțiuni Postman eșuate, acoperire parțială a cozilor și routing-ului, lipsa
alimentării load-ului real și a rerutării aceleiași cereri, plus panouri incomplete. Putem prezenta
funcționalitățile demonstrate, cu aceste limite explicite; nu putem declara laboratorul complet.

## Ce am reparat și verificat

- Toate cele **11 imagini 0.5.0** din Compose au manifest public amd64/arm64 și `latest` aliniat.
- Ambele replici Rules/Record cădeau la pornire: clientul Java gRPC primea o adresă goală.
  Am adăugat `BROKER_GRPC_URL=message-broker:9091`, checker și test de regresie în
  [CPR #292](https://github.com/caramisca/cpr-pad-team-19/pull/292), acum **merged**.
  Cele 13 teste ale checker-elor și verificarea publicării trec.
- Broker #11, merge-uit în `dev` la `5ac3e35`, trece cele **161 teste existente**. Am construit
  separat imaginea locală `pad-lab4-broker:review-5ac3e35` și am repetat probele afectate.
- Emiterea legitimă Credential -> Broker -> **University Record real** întoarce **201**.
  Generarea Applicant/Credential, filtrele cu date din altă sesiune, Content-Type, Location,
  request/instance ID, duplicatele pe ambele replici și REJECTED -> DLC trec.
- **Session real** generează un applicant prin broker, publică `session.closed`, curăță Applicant
  și Credential și creditează un singur shift Player. SSE prin Gateway livrează `state`,
  `applicant-presented`, `closed`.
- Negocierea WebSocket și primirea aceluiași mesaj de **doi clienți locali** trec.
- DLC păstrează mesajele după înlocuirea imaginii și după SIGKILL/restart pe același volum SQLite.
  Aceasta nu dovedește durabilitatea noilor cozi request/reply în memorie.
- Prometheus scrapează **18 ținte UP**: câte două pentru toate cele opt servicii de domeniu,
  plus Broker și Prometheus.

Dovezi fără chei/parole: [lab4-team-acceptance-2026-11-12.json](evidence/lab4-team-acceptance-2026-11-12.json).

## Care versiune a fost testată

CPR integrat: `55564fac1f7751fd5ac5d5fccf5c9113dfe106ef`, după fixul #292.
Broker public main/0.5.0: `b0b3dbacfe6a3747df63f8e10bbe277efd5cfea1`.
Broker nou dev/#11: `5ac3e35ddc048ba4f7e5da4bffce63901d87f51c`.

Prima rulare a folosit toate imaginile publice: 245 cereri, 833 aserțiuni, 34 eșuate.
Rularea finală folosește Broker #11 **construit local**, celelalte imagini publice și colecțiile
corectate: **254 cereri, 860 aserțiuni, 28 eșuate**. Diferența include activarea efectivă a
diagnosticelor private și eliminarea aserțiunilor învechite. Acest build local nu este un release.

Am corectat patru așteptări comune de versiune Gateway și verificarea filtrului Applicant:
rândurile Applicant nu expun `sessionId`; filtrul se verifică prin ID-urile cunoscute ale datasetului.
Nu am schimbat așteptările funcționale ca să ascund erorile de implementare.

## Toate gitlink-urile sunt ultimele versiuni?

Cele cinci repo-uri accesibile au gitlink identic cu ultimul `main` verificat. Cele șase private
coincid cu pointerele de release integrate de proprietari în CPR #290/#291; API-ul lor răspunde
404, deci **nu pot confirma independent ultimul main privat**. Nu este nevoie de acces nou pentru colegi.

| Submodul | SHA pin-uit în CPR | Confirmare |
|---|---|---|
| Applicant | `341e8c36e10830a83ff2fe5596ce8b493b35edf2` | Egal cu main accesibil |
| Credential | `a05ba8bd8e5103de4d3efd343cf8254b59c0bb79` | Egal cu main accesibil |
| Gateway | `3789113b0a5d62e5b0c939f78ebd6fb092a6eb32` | Egal cu main accesibil |
| Service Discovery | `2081f9cd46ffc363cfc0f2ec064687bdbae80c2f` | Egal cu main accesibil |
| Message Broker | `b0b3dbacfe6a3747df63f8e10bbe277efd5cfea1` | Egal cu main; #11 este încă doar în dev |
| Player | `40d80d051ae1c4c572fad8a9d1cdf976ee866b0a` | Pointer de release declarat; main privat neverificat |
| Session | `71ec04a2c96363a010c26b12c6d5e6019aa7e636` | Pointer de release declarat; main privat neverificat |
| Rules | `3c20fd8fa86d475bc770c741bb50a9fb026ffb14` | Pointer de release declarat; main privat neverificat |
| University Record | `e56c875c8f6b926fd637172a6e98db33151c53f1` | Pointer de release declarat; main privat neverificat |
| Moderation | `13c149e9288ab70c1e9ab647e34c94510ad78ced` | Pointer de release declarat; main privat neverificat |
| Discord DMS | `7bb5862c31ef4f64655ee739bd4475a401ea32a1` | Pointer de release declarat; main privat neverificat |

Nu trebuie mutat gitlink-ul Broker direct la dev/#11. După corecții: release nou din main,
imagine publică nouă, apoi PR CPR care aliniază SHA, Compose și checker-ul. Documentația nouă
are propriile PR-uri; până la integrarea lor, un submodul main poate avea încă README-ul vechi.

## Rezultatele Postman finale

| Colecție | Cereri executate | Aserțiuni | Eșuate |
|---|---:|---:|---:|
| Rules | 20 | 52 | 6 |
| University Record | 18 | 47 | 10 |
| Applicant | 24 | 87 | 6 |
| Credential | 29 | 109 | 6 |
| Player | 26 | 111 | 0 |
| Session | 49 | 185 | 0 |
| Moderation | 28 | 88 | 0 |
| DMS | 31 | 90 | 0 |
| Gateway log download | 10 | 41 | 0 |
| Message Broker | 19 | 50 | 0 |

Nu sunt 28 bug-uri diferite: unele cereri eșuate încalcă atât statusul, cât și corpul așteptat.
Colecțiile omit intenționat vechile REST stand-ins și live SSE în Runner; SSE a fost testat separat.
Diagnosticele private sunt activate în rularea finală. Traficul DMS folosește simulatorul proiectului,
fără trimitere către Discord sau către colegi.

### Erori care mai trebuie corectate

**Diana — Rules/Record:**

- Rules acceptă `rules: []` și lipsa `effectiveFrom` cu 201, deși contractul/testele cer 400.
- JSON invalid pe Rules și Record produce 500 `INTERNAL_ERROR`, în loc de 400
  `MALFORMED_REQUEST_BODY`. Este răspunsul adaptorului prin broker, nu un build eșuat.
- `PUT /records/students/1234567890` primește 405 pe calea gRPC; actualizarea și restaurarea
  studentului trebuie implementate/aliniate cu API-ul documentat.
- Pentru metoda greșită, Record întoarce 404 `ROUTE_NOT_FOUND`, nu 405 `METHOD_NOT_ALLOWED`.
- Imaginea Gateway 0.5.0 raportează încă runtime 0.4.1. Am făcut versiunea așteptată configurabilă
  în Postman; versiunea aplicației trebuie aliniată la următorul release, fără suprascrierea 0.5.0.

**Mihai — Applicant/Credential:**

- Adaptoarele gRPC apelează handler-ele de business direct și ocolesc o parte din middleware HTTP.
  JSON invalid dă `VALIDATION_ERROR`, în loc de `MALFORMED_REQUEST`; text/plain dă 400 în loc de 415;
  metoda nesuportată dă 404 în loc de 405. Aliniază statusul, codul JSON și `Allow` cu HTTP.
- Pentru ruta necunoscută, clarifică contractul comun `ROUTE_NOT_FOUND` față de vechea așteptare
  `NOT_FOUND`; păstrează distincția între ruta respinsă de Gateway și ruta ajunsă la serviciu.
- Filtrele și generarea legitimă funcționează; nu trebuie refăcută integrarea Record sau query fix.

## Ce mai are fiecare de făcut, concret

| Cine | Priorități înainte de release |
|---|---|
| Mihai | Alinierea erorilor gRPC Applicant/Credential cu HTTP; integrarea README/Postman actualizate; rerularea colecțiilor după un release nou al serviciilor modificate |
| Diana | Corecțiile Rules/Record de mai sus; request queues pentru toate rutele necesare; alimentare live `update_load`; rerutare după trip cu deadline/idempotență; completare și verificare dashboard-uri; versiunea runtime Gateway |
| Andi | Coordonare cu Diana la rerutare și la durabilitatea request/reply (cozile #11 nu folosesc SQLite); păstrează probele topics/DLC/logs deja trecute; confirmă main-urile private Moderation/DMS și README Lab 4 |
| Daria | Integrarea modurilor/versiunilor finale, testele noilor cozi, release Broker nou după review; confirmarea main-urilor private Player/Session și README Lab 4; apoi CPR dev -> main și gitlink-uri finale |
| Toți | Review pentru PR-urile documentației, rezolvarea eșecurilor funcționale, rerulare comună pe imagini publice finale și prezentare cu dovezi |

### De ce Broker #11 nu închide singur toate restanțele

`REQUEST_QUEUE_SERVICES` are implicit doar `server-rules-service,university-record-service`.
Gateway trimite prin `MessageBroker.Call` doar Applicant/Credential/Rules/Record; celelalte patru
servicii primesc încă HTTP din Gateway. Apelurile în afara setului de cozi sunt directe.
Este progres real, dar nu dovada cozilor Gateway pentru toate serviciile.

Noile cozi sunt `deque` și reply slots în memorie, drenate de un worker. SQLite este folosit
pentru topic events/DLC, nu automat pentru aceste cereri. PR #11 nu adaugă teste specifice pentru
FIFO, corelație concurentă, timeout/cancel, oprire cu cereri în așteptare sau restart.

`update_load` există, fără apelant de producție. Circuitele deja deschise sunt excluse pentru
apelurile următoare; apelul care eșuează nu este reluat în aceeași execuție pe altă replică.
Aceste limite rămân după #11.

## Grafana: ce poți vedea acum

Stack-ul complet izolat este pornit: [Grafana Lab 4](http://localhost:13000/d/lab4-services),
[Prometheus](http://localhost:19090), Gateway `http://localhost:28080`.
Instanța mai veche, parțială, de pe portul 3000 nu este proba întregii echipe.

Am executat toate expresiile dashboard-ului prin API, fără erori PromQL. Sunt 12 panouri
(13 expresii, un panou are două ținte). Nu am validat vizual randarea în browser în această probă.

- Applicant/Credential: rate, 5xx, durată medie și active requests au câte patru serii,
  corespunzătoare celor două replici ale fiecărui serviciu.
- Rules/Record: rata HTTP are serii, active threads are cele patru instanțe; P95 HTTP nu are
  serii deoarece nu există bucket-urile HTTP cerute. 5xx fără serii poate însemna lipsa acelei
  combinații de etichete; nu dovedește singur o aplicație căzută.
- Rules/Record expun separat `grpc_server_*`; traficul business prin gRPC trebuie reflectat
  în panouri, nu dedus numai din rata HTTP a health-check-urilor.
- Broker deliveries/active/pending și Services Up au date.
- Lipsesc panouri business pentru **Player, Session, Moderation și DMS**. `up` singur arată
  scrape availability, nu rata cererilor, erorile sau latența aplicației.

Nu redenumiți o medie în P95. Folosiți histogram buckets reale pentru percentile sau prezentați
corect `sum(duration_sum) / sum(request_count)` ca durată medie. Legendele trebuie să includă instanța.

## Ce lipsește pentru fiecare notă

| Notă | Cerință relevantă | Starea curentă / ce mai trebuie |
|---|---|---|
| 1 | Baza | Fără blocaj tehnic |
| 2 | Broker în limbajul cerut, repo/workflow | Python, repo, CI și imagine există; politica repo este tratată de review-ul proiectului |
| 3 | README, diagramă, Postman actuale | README-uri și diagramă actualizate în PR-uri; trebuie integrate. Postman încă are 28 aserțiuni funcționale eșuate |
| 4 | Endpoint download logs | Colecția logs trece, 41 aserțiuni; criteriile anterioare rămân cumulative |
| 5 | Broker public, mutare comunicare/LB/breaker | Broker public și selecție/breaker există; acoperirea routing-ului trebuie finalizată, cu modurile Lab 4 activate |
| 6 | Subscriber queues + topic queues/SD topics | Topics reale funcționează. #11 adaugă request queues doar pentru două servicii implicit și nu este în release-ul public |
| 7 | Thread per request + lista topics | Implementate; probele și suita Broker trec. Nu anulează restanțele de la 3–6 |
| 8 | gRPC service-to-service, eliminare rute interne | Fluxuri reale gRPC și 404 pentru stand-ins; trebuie închise diferențele contractuale ale adaptoarelor și verificată acoperirea completă |
| 9 | Durable queues, DLC, listare | Topic SQLite/DLC și restart demonstrate. Request queues noi sunt volatile; fiabilitatea lor și cumulativitatea trebuie rezolvate |
| 10 | Rerutare HA, load real, monitorizare utilă | Lipsesc same-call reroute și live load feeding; dashboard incomplet și P95 fără date |

Acesta este un audit tehnic, nu o notă garantată. Criteriile cumulative împiedică declararea
G9/G10 complete doar fiindcă topic store și un dashboard există.

## README-uri și ordinea finală de release

PR-uri de documentație pregătite pentru cele cinci servicii accesibile și pentru CPR:

- [Applicant #14](https://github.com/caramisca/applicant-service/pull/14)
- [Credential #15](https://github.com/caramisca/credential-service/pull/15)
- [Gateway #29](https://github.com/diana7376/gateway-service/pull/29)
- [Service Discovery #14](https://github.com/DariaRateeva/service-discovery/pull/14)
- [Broker #12](https://github.com/DariaRateeva/message-broker/pull/12)
- CPR: ramura `docs/lab4-current-behavior`, împreună cu acest raport, runbook și corecțiile Postman.

Pentru cele șase repo-uri private, fiecare proprietar trebuie să alinieze README-ul la Lab 4:
versiune/imagine publicată, port HTTP și gRPC, variabilele reale, topics publicate/consumate,
COMMITTED/RETRY/REJECTED și persistență, logs/metrics, pornire/testare și limite cunoscute.
Nu am pretins că am editat fișiere la care nu există acces.

Ordinea după închiderea blocajelor:

1. Feature/docs PR -> dev, cu peer review și CI verde.
2. Repetare testelor pe codul final, inclusiv noile cozi, erorile, HA/load și panourile lipsă.
3. Release-uri noi pentru aplicațiile modificate, prin dev -> main conform politicii proiectului;
   nu suprascrieți tagurile 0.5.0 deja publicate.
4. Verificare manifest amd64/arm64 și `latest` pentru noile imagini.
5. PR CPR cu gitlink-urile **main finale**, tagurile Compose și checker-ul aliniate.
6. Proba completă pe imaginile publice finale; apoi CPR dev -> main prin merge commit și review.

Nu am promovat main și nu am modificat gitlink-uri ca substitut pentru aceste verificări.
