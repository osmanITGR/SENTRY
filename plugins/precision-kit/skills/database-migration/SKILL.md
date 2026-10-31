---
name: database-migration
description: Change database schemas and data safely - migrations with the project's migration tool, backward-compatible expand/contract rollouts, reversible steps, data backfills, indexes without downtime, and verification on a real database. Use for adding/removing/renaming columns or tables, changing types or constraints, indexes, data fixes/backfills, ORM model changes, or local storage schema changes (SQLite, Room, Hive, IndexedDB, Core Data).
---

# Database Migration

Data loss is permanent. Every migration is reversible or explicitly accepted
as irreversible by the user.

## 1. Use the project's tool, never hand-run DDL against shared DBs
Alembic, Django migrations, Prisma Migrate, Drizzle Kit, Knex, TypeORM,
Sequelize, Flyway/Liquibase, Rails, EF Core, golang-migrate/goose, sqlx,
Room `Migration`, sqflite/drift `onUpgrade`. Find existing migrations and
mirror their style/naming. Generate, then **read** the generated SQL.

## 2. Design for zero breakage (expand -> migrate -> contract)
Old code and new code run at the same time during deploys and on users'
devices with older app versions.
- **Add column**: nullable or with a default; backfill separately; add
  NOT NULL later.
- **Rename**: add new -> dual-write -> backfill -> switch reads -> drop old
  in a later release. Never a direct rename on a live system.
- **Drop**: stop using it in code first (release), drop in a later migration.
- **Type change**: new column + backfill + switch, not in-place cast on big tables.
- **Indexes** on large tables: concurrent/online creation
  (`CREATE INDEX CONCURRENTLY`, `ALGORITHM=INPLACE`), outside a transaction if required.
- **Backfills**: batched, idempotent, resumable; not inside the schema migration
  for large tables.
- Mobile/local DBs: every historical version must upgrade to the new one
  (v1->vN, not just vN-1->vN); never drop user data on upgrade.

## 3. Write both directions
Implement `down`/rollback where the tool supports it; if it truly can't be
reversed (data dropped), say so and get the user's explicit OK.

## 4. Verify on a real database (local/container, never production)
- Fresh DB: run all migrations from zero.
- Existing data: seed realistic rows with the *old* schema, migrate up, check
  data integrity (counts, nulls, constraints), migrate down, up again.
- Run the app/tests against the migrated schema (`verification-gate`).
- ORM models, types, fixtures, factories and seeds updated in the same change.

## 5. Report
Migration name, what it does, lock/downtime risk, rollback path, required
deploy order (e.g. "deploy code first, then migration 0042").
