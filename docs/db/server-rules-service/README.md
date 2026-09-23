# server-rules-service — DB scripts

MongoDB is schemaless, so there is no DDL script to publish here. Demo seed data (one default
ruleset) is created by the application itself on first boot
(`DemoDataSeeder` in `services/server-rules-service`), and skips itself once any ruleset already
exists, so it is safe across restarts of a persistent database.
