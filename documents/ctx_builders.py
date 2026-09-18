from django.contrib.auth import get_user_model


User = get_user_model()

def base_user_context(user: User):
    ui = user.user_info
    pd = user.personal_data

    fio = " ".join(filter(None, [
        (pd.last_name if pd and pd.last_name else user.last_name),
        (pd.first_name if pd and pd.first_name else user.first_name),
        (pd.middle_name if pd else None),
    ]))

    return {
        "user": {
            "id": str(user.id),
            "username": user.username,
            "email": pd.email if pd and pd.email else user.email,
            "phone": pd.phone if pd else "",
            "fio": fio,
            "first_name": pd.first_name if pd and pd.first_name else user.first_name,
            "last_name": pd.last_name if pd and pd.last_name else user.last_name,
            "middle_name": (pd.middle_name if pd else ""),
        },
        "passport": {
            "series": pd.passport_series if pd else "",
            "number": pd.passport_number if pd else "",
            "issued_at": pd.passport_issued_at.strftime("%d.%m.%Y") if (pd and pd.passport_issued_at) else "",
            "issued_by": pd.passport_issued_by if pd else "",
            "dept_code": pd.passport_department_code if pd else "",
        },
        "address": {
            "registration": pd.registration_address if pd else "",
            "city": getattr(ui, "city", "") if ui else "",
        },
        "bank": {
            "name": pd.bank_name if pd else "",
            "account": pd.bank_account if pd else "",
            "bik": pd.bank_bik if pd else "",
            "correspondent": pd.bank_correspondent_account if pd else "",
        },
        "personal": {
            "snils": pd.snils if pd else "",
        }
    }


def merge_context(base: dict, extra: dict) -> dict:
    ctx = dict(base)
    for k, v in (extra or {}).items():
        ctx[k] = v
    return ctx
