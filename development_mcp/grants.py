"""Print reviewable PostgreSQL SQL; never connect or apply grants automatically."""

from .database import ROLE
from .schema import TABLES, registry_version, validate_registry


def grant_sql(update=False):
    validate_registry()
    lines = [
        "-- Run as database administrator in the application's database using psql.",
        f"-- Registry version: {registry_version()}",
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
    ]
    if update:
        # Rebuild only this dedicated role's direct table/column ACLs. No PUBLIC
        # privileges, memberships, ownership, objects or data are changed.
        lines.append(f"""DO $mcp$
DECLARE entry record;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}'
                   AND NOT (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls))
       OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member = '{ROLE}'::regrole) THEN
        RAISE EXCEPTION 'Unsafe or missing MCP reader role';
    END IF;
    FOR entry IN
        SELECT n.nspname, c.relname,
               string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum) AS columns
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
        GROUP BY n.nspname, c.relname
    LOOP
        EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM %I', entry.nspname, entry.relname, '{ROLE}');
        EXECUTE format('REVOKE ALL PRIVILEGES (%s) ON TABLE %I.%I FROM %I', entry.columns, entry.nspname, entry.relname, '{ROLE}');
    END LOOP;
END
$mcp$;""")
    else:
        lines += [
            "-- A fresh dedicated role is required; reruns intentionally fail at CREATE ROLE.",
            f"CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;",
        ]
    lines += [
        f"ALTER ROLE {ROLE} SET default_transaction_read_only = on;",
        f"ALTER ROLE {ROLE} SET statement_timeout = '10s';",
        f"ALTER ROLE {ROLE} SET lock_timeout = '2s';",
        "SELECT format('GRANT CONNECT ON DATABASE %I TO " + ROLE + "', current_database()) \\gexec",
        f"GRANT USAGE ON SCHEMA public TO {ROLE};",
    ]
    for table, spec in TABLES.items():
        columns = ", ".join('"' + column + '"' for column in spec.columns)
        lines.append(f'GRANT SELECT ({columns}) ON TABLE public."{table}" TO {ROLE};')
    lines.append("COMMIT;")
    if not update:
        lines += ["-- Assign a SCRAM password interactively; it is never put in generated SQL.", f"\\password {ROLE}"]
    lines.append("-- No default privileges: newly added tables/columns remain inaccessible.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="Synchronize an existing reader's grants; preserve password and data")
    args = parser.parse_args()
    print(grant_sql(update=args.update), end="")
