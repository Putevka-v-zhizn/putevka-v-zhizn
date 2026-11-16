"""Propose a reviewed registry declaration from live Django metadata, without queries."""

import hashlib
import re

from django.db import models

from .schema import PROGRAMS, TABLES, filter_path


class DraftError(Exception):
    pass


def _name(value):
    value = value.lower()
    return value if len(value) <= 48 else value[:39] + '_' + hashlib.sha256(value.encode()).hexdigest()[:8]


def draft_model(model, programs=(), via=None):
    if model._meta.pk.column != 'id' or any(model._meta.parents.values()):
        raise DraftError('custom_primary_key_or_multi_table_inheritance_needs_manual_mapping')
    if not set(programs) <= PROGRAMS.keys():
        raise DraftError('unknown_program')
    candidates = []
    for field in model._meta.concrete_fields:
        if field.is_relation and (field.many_to_one or field.one_to_one):
            parent = field.related_model._meta.db_table
            reachable = [filter_path(p, parent) is not None for p in (programs or PROGRAMS)] if parent in TABLES else []
            if reachable and (all(reachable) if programs else any(reachable)):
                candidates.append(field)
    if via:
        candidates = [field for field in candidates if field.name == via]
    elif len(candidates) > 1:
        preferred = [field for field in candidates if field.name in {'user', 'target_user'}]
        if len(preferred) == 1:
            candidates = preferred
    if len(candidates) != 1:
        raise DraftError('choose_parent_with_via: ' + ', '.join(sorted(field.name for field in candidates)))
    parent = candidates[0]
    if parent.column != parent.attname or parent.target_field.column not in TABLES[parent.related_model._meta.db_table].columns:
        raise DraftError('custom_join_needs_manual_declaration')
    output, identities, excluded, filters = [], [], [], []
    age_field = None
    for field in model._meta.get_fields():
        name = field.name
        if not field.concrete or field.primary_key or field.is_relation:
            if field.concrete and field != parent:
                excluded.append((name, 'relation; review replay dependencies'))
            continue
        if field.column != name:
            excluded.append((name, 'custom column; requires explicit mapping'))
            continue
        if re.search(r'(?:^|_)(?:password|secret|token|key|hash|salt|code|error|payload|cookie|permissions|id)(?:_|$)', name) or name in {'is_staff', 'is_superuser'}:
            excluded.append((name, 'secret, identifier or technical state'))
            continue
        if isinstance(field, (models.FileField, models.BinaryField, models.URLField, models.UUIDField)):
            excluded.append((name, 'file, URL or identifier'))
            continue
        if name in {'birth_date', 'date_of_birth'} and isinstance(field, models.DateField) and not isinstance(field, models.DateTimeField):
            age_field = name
            continue
        if isinstance(field, (models.DateField, models.DateTimeField, models.JSONField)):
            excluded.append((name, 'date/JSON requires explicit review'))
            continue
        kind = None
        if isinstance(field, models.EmailField) or re.search(r'(?:phone|email|telegram|username|contact|^vk$)', name):
            kind = 'contact'
        elif re.search(r'(?:passport|snils|bank_account|bank_bik|correspondent_account)', name):
            excluded.append((name, 'document or banking details; opt in manually'))
            continue
        elif 'address' in name:
            kind = 'address'
        elif name in {'city', 'region', 'final_city', 'birth_place'}:
            kind = 'place'
        elif name in {'school_name', 'company_name', 'employer_name', 'bank_name'}:
            kind = 'organization'
        elif name == 'name' or name in {'first_name', 'last_name', 'middle_name'} or name.endswith(('_name', '_fio')):
            kind = 'person'
        if kind and isinstance(field, (models.CharField, models.TextField)):
            identities.append((name, kind))
            continue
        if field.unique or isinstance(field, models.SlugField):
            excluded.append((name, 'unique/slug identifier'))
            continue
        if not isinstance(field, (models.CharField, models.TextField, models.BooleanField, models.IntegerField, models.FloatField, models.DecimalField)):
            excluded.append((name, 'unsupported field type'))
            continue
        output.append(name)
        prefix = _name(model._meta.model_name + '_' + name)
        choices = tuple(value for value, _ in field.flatchoices if isinstance(value, str) and value)
        if field.choices and choices and len(choices) <= 32 and isinstance(field, (models.CharField, models.TextField)):
            filters.append(f'CaseFilter({prefix!r}, "choice", {name!r}, choices={choices!r})')
        elif isinstance(field, models.TextField):
            filters.append(f'CaseFilter({_name("has_" + prefix)!r}, "text", {name!r})')
        elif isinstance(field, (models.IntegerField, models.FloatField, models.DecimalField)):
            filters.append(f'CaseFilter({prefix!r}, "number", {name!r})')
    filters.append(f'CaseFilter({_name(model._meta.model_name + "_count")!r}, "count")')
    parent_table = parent.related_model._meta.db_table
    args = [repr(parent_table), repr(parent.column)]
    if parent.target_field.column != 'id':
        args.append('source_column=' + repr(parent.target_field.column))
    if programs:
        args.append('programs=' + repr(tuple(sorted(set(programs)))))
    lines = [f'# Draft for {model._meta.label}; review before adding to TABLES.',
             '# No registry, database data or ACLs were changed.', f'{model._meta.db_table!r}: Table(',
             f'    output={tuple(output)!r},', f'    identities={tuple(identities)!r},',
             '    loads=(Load(' + ', '.join(args) + '),),']
    if age_field:
        lines.append(f'    age_field={age_field!r},')
    lines += ['    filters=(', *['        ' + value + ',' for value in filters], '    ),', '),']
    lines += [f'# Excluded {name}: {reason}' for name, reason in sorted(excluded)]
    return '\n'.join(lines) + '\n'
