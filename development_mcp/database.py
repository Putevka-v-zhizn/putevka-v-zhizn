"""Small, parameterized PostgreSQL reader with column-level privileges."""

from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .schema import PROGRAMS, TABLES

ROLE = "putevka_mcp_reader"
MAX_ROWS = 500
MAX_CASE_CHARACTERS = 2_000_000


class AccessDenied(Exception):
    pass


class CaseTooLarge(Exception):
    pass


class Reader:
    def __init__(self, connection):
        self.connection = connection
        self.rows = 0
        self.characters = 0
        self.seen = set()
        self.data_as_of = datetime.now(timezone.utc).isoformat()

    def select(self, table, column=None, values=(), *, columns=None, limit=MAX_ROWS + 1, offset=0, status=None):
        spec = TABLES[table]
        columns = tuple(columns or spec.columns)
        if not set(columns) <= set(spec.columns) or (column and column not in spec.columns):
            raise AccessDenied()
        query = sql.SQL("SELECT {} FROM public.{}").format(
            sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table))
        conditions, params = [], []
        if column:
            if not values:
                return []
            conditions.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(column)))
            params.append(list(values))
        if status is not None:
            status_column, status_value = status
            if status_column not in spec.output:
                raise AccessDenied()
            conditions.append(sql.SQL("{} = %s").format(sql.Identifier(status_column)))
            params.append(status_value)
        if conditions:
            query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        query += sql.SQL(" ORDER BY id LIMIT %s OFFSET %s")
        params.extend((limit, offset))
        return self.connection.execute(query, params).fetchall()

    def collect(self, table, column, values):
        rows = self.select(table, column, values)
        if len(rows) > MAX_ROWS:
            raise CaseTooLarge()
        fresh = [row for row in rows if (table, row["id"]) not in self.seen]
        self.seen.update((table, row["id"]) for row in fresh)
        self.rows += len(fresh)
        self.characters += sum(len(str(value)) for row in fresh for value in row.values() if value is not None)
        if self.rows > MAX_ROWS or self.characters > MAX_CASE_CHARACTERS:
            raise CaseTooLarge()
        return [(table, row) for row in rows]

    def list_roots(self, program, status, offset, limit, filters=None):
        from .selection import list_query, normalize_filters
        query, params = list_query(program, status, normalize_filters(program, filters), offset, limit)
        return self.connection.execute(query, params).fetchall()

    def root_ids(self, program):
        # Scan identifiers only; never load all cases or text for ID resolution.
        table = PROGRAMS[program][0]
        with self.connection.cursor(name="mcp_case_ids") as cursor:
            cursor.execute(sql.SQL("SELECT id FROM public.{} ORDER BY id").format(sql.Identifier(table)))
            for row in cursor:
                yield row["id"]

    def load_case(self, program, pk):
        root_table = PROGRAMS[program][0]
        records = self.collect(root_table, "id", [pk])
        if not records:
            return []
        # Walk only explicitly declared load rules. The per-rule frontier makes
        # declaration order irrelevant and terminates cycles without duplicate rows.
        indexed = {(table, row["id"]): row for table, row in records}
        queried = {}
        while True:
            progressed = False
            for table, spec in TABLES.items():
                for number, load in enumerate(spec.loads):
                    if not load.applies(program):
                        continue
                    values = {row.get(load.source_column) for (source, _), row in indexed.items()
                              if source == load.source and row.get(load.source_column) is not None}
                    frontier = values - queried.setdefault((table, number), set())
                    if not frontier:
                        continue
                    queried[(table, number)].update(frontier)
                    for name, row in self.collect(table, load.column, sorted(frontier)):
                        key = (name, row["id"])
                        if key not in indexed:
                            indexed[key] = row
                            progressed = True
            if not progressed:
                break
        return [(table, row) for (table, _), row in indexed.items()]


def audit_privileges(connection):
    """Reject an accidentally configured owner/admin or an overly broad reader."""
    role = connection.execute("""SELECT current_user AS name, rolsuper, rolcreaterole, rolcreatedb,
        rolreplication, rolbypassrls FROM pg_roles WHERE rolname = current_user""").fetchone()
    if role["name"] != ROLE or any(role[k] for k in role if k != "name"):
        raise AccessDenied()
    if connection.execute("SELECT 1 FROM pg_auth_members WHERE member = current_user::regrole LIMIT 1").fetchone():
        raise AccessDenied()
    if connection.execute("SELECT has_database_privilege(current_database(), 'CREATE') AS allowed").fetchone()["allowed"]:
        raise AccessDenied()
    if connection.execute("""SELECT 1 FROM pg_namespace
        WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema'
        AND has_schema_privilege(oid, 'CREATE') LIMIT 1""").fetchone():
        raise AccessDenied()
    tables = connection.execute("""SELECT n.nspname, c.relname,
        has_table_privilege(c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') AS writable,
        c.relowner = current_user::regrole AS owned,
        has_table_privilege(c.oid, 'SELECT') AS readable
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind IN ('r','p','v','m','f') AND n.nspname NOT LIKE 'pg_%'
        AND n.nspname <> 'information_schema'""").fetchall()
    for table in tables:
        if table["writable"] or table["owned"] or table["readable"]:
            # Require column grants even on allowed tables; prevents future columns leaking.
            raise AccessDenied()
    columns = connection.execute("""SELECT n.nspname, c.relname, a.attname,
        has_column_privilege(c.oid, a.attnum, 'SELECT') AS readable,
        has_column_privilege(c.oid, a.attnum, 'INSERT,UPDATE,REFERENCES') AS writable
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r','p','v','m','f')
        AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'""").fetchall()
    granted = set()
    for column in columns:
        key = (column["nspname"], column["relname"], column["attname"])
        if column["writable"]:
            raise AccessDenied()
        if column["readable"]:
            granted.add(key)
    expected = {("public", table, column) for table, spec in TABLES.items() for column in spec.columns}
    if granted != expected:
        raise AccessDenied()


class Database:
    def __init__(self, url):
        self.url = url

    @contextmanager
    def read(self):
        # Never reuse the application's connection, settings or credentials.
        with psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10,
                             application_name="putevka-development-mcp",
                             options="-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=2000") as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            audit_privileges(connection)
            yield Reader(connection)
