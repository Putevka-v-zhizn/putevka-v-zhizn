"""Create a separate, clearly labelled QA season without participant answers."""
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from config import BASE_URL
from nto_travel.models import NtoCampaign, NtoConsentRevision, NtoProfile


@transaction.atomic
def create_demo():
    if urlsplit(BASE_URL).hostname != "qa.putevka-v-zhizn.dmitrylem.ru":
        raise RuntimeError("This utility is restricted to the QA site")
    print("Existing QA seasons:", list(NtoCampaign.objects.values_list("slug", "state")))
    campaign = NtoCampaign.objects.filter(slug="qa-nto-2026-2027").first()
    if campaign:
        if not campaign.accepting:
            raise RuntimeError("Existing demo season is closed; it was not changed")
        print("Demo season already open:", campaign.slug)
        return campaign
    consent, _ = NtoConsentRevision.objects.get_or_create(
        version="qa-demo-20261020",
        defaults={"text": "Тестовое согласие для проверки анкеты на QA. Используйте только вымышленные данные. Этот текст не является утверждённым согласием для реального сбора персональных данных."},
    )
    campaign = NtoCampaign.objects.create(
        slug="qa-nto-2026-2027", academic_year="QA-2026/2027",
        name="Тестовый отбор НТО 2026/2027 (QA)",
        opens_at=timezone.now() - timedelta(days=1),
        closes_at=datetime(2027, 7, 1, tzinfo=ZoneInfo("Europe/Moscow")),
        consent_revision=consent,
    )
    for code, name, city in [
        ("QA-DATA", "Анализ данных", "Казань"),
        ("QA-AI", "Искусственный интеллект", "Москва"),
        ("QA-ROBOT", "Робототехника", "Томск"),
        ("QA-SECURITY", "Информационная безопасность", "Санкт-Петербург"),
        ("QA-ENERGY", "Энергетика", "Новосибирск"),
    ]:
        NtoProfile.objects.create(campaign=campaign, external_code=code, name="Тестовый профиль: " + name, final_city=city)
    campaign.state = NtoCampaign.State.PUBLISHED
    campaign.save()
    assert campaign.accepting
    print("Created open QA season:", campaign.slug, "profiles:", campaign.profiles.count(), "applications:", campaign.applications.count() if hasattr(campaign, "applications") else 0)
    return campaign


if "SEED_QA_NTO" in globals():
    create_demo()
