"""Compile only declared case features; no text or user SQL leaves PostgreSQL."""

import math

from psycopg import sql

from .schema import PROGRAMS, case_filters, filter_path


class InvalidFilters(Exception):
    pass


def normalize_filters(program, filters):
    available = case_filters(program)
    if filters is None:
        return {}
    if not isinstance(filters, dict) or len(filters) > len(available):
        raise InvalidFilters()
    result = {}
    for name, value in filters.items():
        if name not in available:
            raise InvalidFilters()
        definition = available[name][1]
        if definition.kind == "text":
            if type(value) is not bool:
                raise InvalidFilters()
        elif definition.kind == "choice":
            if not isinstance(value, str) or value not in definition.choices:
                raise InvalidFilters()
        else:
            if not isinstance(value, dict) or not value or not value.keys() <= {"min", "max"}:
                raise InvalidFilters()
            for bound in value.values():
                if type(bound) not in {int, float} or abs(bound) > 10**12 or not math.isfinite(bound):
                    raise InvalidFilters()
                if definition.kind == "count" and (type(bound) is not int or bound < 0):
                    raise InvalidFilters()
            if value.get("min", -math.inf) > value.get("max", math.inf):
                raise InvalidFilters()
            value = {key: value[key] for key in ("min", "max") if key in value}
        result[name] = value
    return dict(sorted(result.items()))


def metric_sql(program, table, definition):
    path = filter_path(program, table)
    if path is None:
        raise InvalidFilters()
    joins, correlation = sql.SQL(""), sql.SQL("TRUE")
    alias = "r"
    for index, (target, load) in enumerate(path):
        previous, alias = alias, f"f{index}"
        equality = sql.SQL("{}.{} = {}.{}").format(sql.Identifier(alias), sql.Identifier(load.column),
                                                  sql.Identifier(previous), sql.Identifier(load.source_column))
        if index == 0:
            joins = sql.SQL("public.{} AS {}").format(sql.Identifier(target), sql.Identifier(alias))
            correlation = equality
        else:
            joins += sql.SQL(" JOIN public.{} AS {} ON {}").format(sql.Identifier(target), sql.Identifier(alias), equality)
    field = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(definition.field or "id"))
    if definition.kind == "text":
        present = sql.SQL("COALESCE({}, '') ~ '[^[:space:]]'").format(field)
        if not path:
            return present
        return sql.SQL("EXISTS (SELECT 1 FROM {} WHERE {} AND {})").format(joins, correlation, present)
    if definition.kind == "count":
        value = sql.SQL("COUNT(DISTINCT {})").format(field)
        if not path:
            return sql.SQL("1::bigint")
    elif definition.kind == "number":
        if not path:
            return field
        value = sql.SQL("MAX({})").format(field)
    else:
        # Return registry literals only, even if a database status contains PII.
        known = sql.SQL("CASE {} {} ELSE 'unknown' END").format(field, sql.SQL(" ").join(
            sql.SQL("WHEN {} THEN {}").format(sql.Literal(choice), sql.Literal(choice)) for choice in definition.choices))
        nonempty = sql.SQL("{} IS NOT NULL AND {} <> ''").format(field, field)
        if not path:
            return sql.SQL("CASE WHEN {} THEN ARRAY[{}] ELSE ARRAY[]::text[] END").format(nonempty, known)
        value = sql.SQL("COALESCE(ARRAY_AGG(DISTINCT {}) FILTER (WHERE {}), ARRAY[]::text[])").format(known, nonempty)
    return sql.SQL("(SELECT {} FROM {} WHERE {})").format(value, joins, correlation)


def list_query(program, status, filters, offset, limit):
    table, status_column, _ = PROGRAMS[program]
    available = case_filters(program)
    metrics = {name: metric_sql(program, target, definition) for name, (target, definition) in available.items()}
    columns = [sql.SQL('r.id'), sql.SQL('r.{}').format(sql.Identifier(status_column))]
    columns += [sql.SQL("{} AS {}").format(expression, sql.Identifier("feature_" + name)) for name, expression in metrics.items()]
    query = sql.SQL("SELECT {} FROM public.{} AS r").format(sql.SQL(", ").join(columns), sql.Identifier(table))
    conditions, params = [], []
    if status is not None:
        conditions.append(sql.SQL("r.{} = %s").format(sql.Identifier(status_column)))
        params.append(status)
    for name, value in filters.items():
        expression = metrics[name]
        definition = available[name][1]
        if definition.kind == "choice":
            conditions.append(sql.SQL("%s = ANY(({})::text[])").format(expression))
            params.append(value)
        elif definition.kind == "text":
            conditions.append(sql.SQL("({}) = %s").format(expression))
            params.append(value)
        else:
            for key, operator in (("min", ">="), ("max", "<=")):
                if key in value:
                    conditions.append(sql.SQL("{} {} %s").format(expression, sql.SQL(operator)))
                    params.append(value[key])
    if conditions:
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
    query += sql.SQL(" ORDER BY r.id LIMIT %s OFFSET %s")
    return query, params + [limit, offset]
