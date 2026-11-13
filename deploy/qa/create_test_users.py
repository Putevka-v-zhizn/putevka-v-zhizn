"""Executed by the QA workflow inside manage.py shell; ACCOUNTS contains hashes."""
import re
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher
from django.db import transaction

from config import BASE_URL
from core.models import RegistrationPersonalData, UserProgramPreferences
from nto_travel.models import NtoApplication
from scholar_form.models import UserInfo


def create_accounts(accounts):
    if urlsplit(BASE_URL).hostname != "qa.putevka-v-zhizn.dmitrylem.ru":
        raise RuntimeError("This utility is restricted to the QA site")
    if not isinstance(accounts, list) or not 1 <= len(accounts) <= 10:
        raise ValueError("Expected 1–10 test accounts")
    user_model = get_user_model()
    with transaction.atomic():
        for record in accounts:
            username = record["username"]
            if not re.fullmatch(r"qa\.[a-z0-9.]+@example\.invalid", username):
                raise ValueError("Only dedicated QA test usernames are allowed")
            mode = record["program"]
            if mode not in {"nto", "main", "both", "choose"}:
                raise ValueError("Unknown program")
            identify_hasher(record["password_hash"])
            if user_model.objects.filter(username=username).exists() or user_model.objects.filter(email=username).exists():
                raise ValueError("Account already exists; existing accounts are never changed")
            user = user_model.objects.create(
                username=username, email=username, password=record["password_hash"],
                is_active=True, is_staff=False, is_superuser=False,
            )
            RegistrationPersonalData.objects.create(
                user=user, email=username, password=user.password,
                email_verified=True, current_step="finish",
            )
            UserProgramPreferences.objects.create(
                user=user, main_enabled=mode in {"main", "both"},
                nto_enabled=mode in {"nto", "both"},
                active_program="" if mode == "choose" else "nto" if mode in {"nto", "both"} else "main",
            )
            info, _ = UserInfo.objects.get_or_create(user=user)
            if info.form_status != "draft" or info.first_name or info.last_name or info.phone:
                raise RuntimeError("Expected an empty main questionnaire")
            if NtoApplication.objects.filter(user=user).exists():
                raise RuntimeError("Expected no NTO applications")
    print(f"Created {len(accounts)} active QA accounts with empty questionnaires")


if "ACCOUNTS" in globals():
    create_accounts(ACCOUNTS)
