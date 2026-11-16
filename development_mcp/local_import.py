"""Explicit local-only replay. No model save() hooks, signals or external services."""

from datetime import date, timedelta
from decimal import Decimal
import hashlib
import math
import re

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections, models, transaction
from django.utils import timezone

from .bundle import BundleError, validate_bundle
from .schema import TABLES, registry_version


class ImportCaseError(Exception):
    pass


def ensure_local(database):
    if not settings.DEBUG or not getattr(settings, 'DEVELOPMENT_MCP_IMPORT_ENABLED', False):
        raise ImportCaseError('local_import_disabled')
    connection = connections[database]
    if connection.vendor == 'sqlite':
        return
    config = connection.settings_dict
    if (connection.vendor != 'postgresql' or str(config.get('HOST', '')) not in {'', 'localhost', '127.0.0.1', '::1', 'db'}
            or not re.fullmatch(r'[A-Za-z0-9_-]+_(?:dev|test)', str(config.get('NAME', '')))):
        raise ImportCaseError('only_local_development_database_allowed')


def _default(field):
    if field.has_default():
        return field.get_default()
    if field.null:
        return None
    if isinstance(field, models.BooleanField):
        return False
    if isinstance(field, (models.IntegerField, models.FloatField, models.DecimalField)):
        minimum = max([0] + [v.limit_value for v in field.validators if v.__class__.__name__ == 'MinValueValidator' and isinstance(v.limit_value, (int, float, Decimal))])
        return Decimal(minimum) if isinstance(field, models.DecimalField) else minimum
    if isinstance(field, models.DateTimeField):
        return timezone.now()
    if isinstance(field, models.DateField):
        return date(2000, 1, 1)
    if isinstance(field, models.JSONField):
        return []
    if isinstance(field, (models.CharField, models.TextField, models.FileField)):
        return ''
    raise ImportCaseError('unsupported_required_field')


def _insert(model, database, values):
    obj = model(**values)
    for field in model._meta.concrete_fields:
        if field.primary_key or field.auto_created or getattr(field, 'auto_now', False) or getattr(field, 'auto_now_add', False):
            continue
        value = getattr(obj, field.attname)
        if value is None and not field.null:
            if field.is_relation:
                raise ImportCaseError('missing_required_relation')
            setattr(obj, field.attname, _default(field))
    # bulk_create deliberately bypasses custom save(), pre_save and post_save signals.
    model.objects.using(database).bulk_create([obj])
    if obj.pk is None:
        raise ImportCaseError('backend_cannot_return_new_ids')
    return obj


def _field_values(model, record):
    result = {}
    for name, value in record['fields'].items():
        if name == 'age_group':
            continue
        field = model._meta.get_field(name)
        if field.is_relation or isinstance(field, (models.FileField, models.DateField)):
            raise ImportCaseError('unsupported_export_field')
        if value is None and not field.null:
            value = _default(field)
        if value is not None:
            value = field.to_python(value)
            if isinstance(value, (float, Decimal)) and not math.isfinite(value):
                raise ImportCaseError('invalid_numeric_value')
        result[name] = value
    return result


def import_bundle(bundle, database='default', password=None, suffix=''):
    ensure_local(database)
    validate_bundle(bundle)
    if suffix and not re.fullmatch(r'[a-z0-9_-]{1,16}', suffix):
        raise ImportCaseError('invalid_suffix')
    User = get_user_model()
    username = 'mcp_' + bundle['case_id'][:24] + ('_' + suffix if suffix else '')
    model_map = {model._meta.db_table: model for model in apps.get_models()}
    if any(record['table'] not in model_map for record in bundle['records']):
        raise ImportCaseError('unknown_local_model')
    by_id = {record['id']: record for record in bundle['records']}
    created, helpers = {}, []
    namespace = hashlib.sha256(username.encode()).hexdigest()[:12]

    with transaction.atomic(using=database):
        if User.objects.using(database).filter(username=username).exists():
            raise ImportCaseError('already_imported_use_another_suffix')
        user = User(username=username, email=username + '@example.invalid', first_name='Участник', last_name='MCP',
                    is_active=True, is_staff=False, is_superuser=False)
        user.set_password(password) if password else user.set_unusable_password()
        User.objects.using(database).bulk_create([user])

        def synthetic(table, **values):
            obj = _insert(model_map[table], database, values)
            helpers.append(table)
            return obj

        def campaign():
            consent = synthetic('nto_travel_ntoconsentrevision', version='mcp-' + namespace + '-' + str(len(helpers)),
                                text='Тестовое локальное согласие. Не является согласием реального участника.')
            return synthetic('nto_travel_ntocampaign', slug='mcp-' + namespace + '-' + str(len(helpers)),
                             academic_year='mcp-' + namespace + '-' + str(len(helpers)), name='Локальный случай MCP',
                             opens_at=timezone.now() - timedelta(days=30), closes_at=timezone.now() + timedelta(days=365),
                             state='published', consent_revision_id=consent.pk)

        def create(token):
            if token in created:
                return created[token]
            if token in visiting:
                raise ImportCaseError('cyclic_required_relations')
            visiting.add(token)
            record = by_id[token]
            table, model = record['table'], model_map[record['table']]
            values = _field_values(model, record)
            for field in model._meta.concrete_fields:
                if not field.is_relation or field.primary_key:
                    continue
                target = record['links'].get(field.name)
                if target:
                    values[field.attname] = create(target).pk
                elif field.related_model == User and field.name in {'user', 'target_user'}:
                    values[field.attname] = user.pk
            if table == 'scholar_form_userinfo':
                values.update(first_name='Участник', last_name='MCP', email=user.email, phone='', address='', city='[Место]')
                group = record['fields'].get('age_group', 'unknown')
                years = {'under_14': 12, '14_17': 16, '18_24': 20, '25_plus': 30}.get(group)
                values['birth_date'] = date(timezone.now().year - years, 1, 1) if years else None
            elif table == 'nto_travel_ntocampaign':
                obj = campaign()
                created[token] = obj
                visiting.remove(token)
                return obj
            elif table == 'nto_travel_ntoapplication':
                values.update(first_name='Участник', last_name='MCP', email=user.email, city='[Место]', region='[Регион]', final_city='[Место]')
                if not values.get('campaign_id'):
                    values['campaign_id'] = campaign().pk
            elif table == 'nto_travel_ntoapplicationprofile':
                application = model_map['nto_travel_ntoapplication'].objects.using(database).get(pk=values['application_id'])
                profile = synthetic('nto_travel_ntoprofile', campaign_id=application.campaign_id,
                                    external_code='mcp-' + token, name=values.get('name_snapshot') or 'Тестовый профиль', final_city='[Место]', is_active=True)
                values.update(profile_id=profile.pk, city_snapshot='[Место]')
            elif table == 'family_income_familyincomedocument':
                document = synthetic('documents_document', user_id=user.pk, caption='Тестовый документ MCP: файл не экспортирован', file='')
                values['document_id'] = document.pk
            elif table == 'family_income_incomeevidence':
                values['owner_name'] = '[Человек]'
            elif table == 'family_income_socialbenefitevidence':
                values['recipient_name'] = '[Человек]'
            if table == 'family_income_incomeyear':
                obj = model.objects.using(database).filter(year=values['year']).first()
                obj = obj or _insert(model, database, values)
            else:
                obj = _insert(model, database, values)
            created[token] = obj
            visiting.remove(token)
            return obj

        visiting = set()
        for record in bundle['records']:
            create(record['id'])
        if not model_map['scholar_form_userinfo'].objects.using(database).filter(user=user).exists():
            synthetic('scholar_form_userinfo', user_id=user.pk, first_name='Участник', last_name='MCP', email=user.email)
        nto_apps = list(model_map['nto_travel_ntoapplication'].objects.using(database).filter(user=user).select_related('campaign')) if 'nto_travel_ntoapplication' in model_map else []
        for application in nto_apps:
            if not model_map['nto_travel_ntoprofile'].objects.using(database).filter(campaign_id=application.campaign_id).exists():
                synthetic('nto_travel_ntoprofile', campaign_id=application.campaign_id, external_code='mcp-fallback',
                          name='Тестовый профиль', final_city='[Место]', is_active=True)
        if 'core_userprogrampreferences' in model_map:
            synthetic('core_userprogrampreferences', user_id=user.pk,
                      main_enabled=bundle['program'] != 'nto', nto_enabled=bool(nto_apps),
                      active_program='nto' if bundle['program'] == 'nto' else 'main')
        urls = ['/form/personal-info/']
        if bundle['program'] == 'main':
            urls += ['/motivation/', '/form/testing/', '/form/video/']
        elif bundle['program'] == 'family_income':
            urls.append('/family-income/')
        urls += [f'/nto/{application.campaign.slug}/application/' for application in nto_apps]
        return {'username': username, 'user_id': user.pk, 'records': len(created), 'synthetic_records': len(helpers),
                'urls': urls, 'staff_url': f'/staff/scholars/{user.pk}/',
                'registry_matches': bundle['registry_version'] == registry_version()}
