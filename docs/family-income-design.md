# Вкладка «Семья и доход»: проект первой итерации

## Статус и границы

Документ описывает отдельное Django-приложение `family_income`. В первой
итерации автоматический расчёт дохода и автоматический пересчёт намеренно не
реализуются: итог за каждый год вручную вводит сотрудник Фонда.

Новое приложение не заменяет и не изменяет семейные поля первоначальной
анкеты `scholar_form.UserInfo`. Они сохраняют ответ кандидата на момент
заполнения анкеты. Подтверждённые сведения и решения сотрудников хранятся
только в `family_income`.

Существующая модель `documents.Document` также не изменяется. Новый модуль
связывает с ней документы через отдельную модель.

## Интеграции

```text
User --1:1-- UserInfo --1:1-- FamilyIncomeCase
                              |
                              +--1:N-- FamilyIncomeDocument --1:1-- documents.Document
                              |              |
                              |              +--0:1-- IncomeEvidence
                              |              +--0:1-- SocialBenefitEvidence
                              |
                              +--1:N-- FamilyIncomeDecision
                              +--1:N-- FamilyIncomeAuditEvent
```

`FamilyIncomeDocument.document` — связь `OneToOne`. Поэтому один загруженный
`Document` не может состоять более чем в одной категории или быть привязан к
нескольким характеристикам семьи.

## Модели

### `FamilyIncomeCase`

Карточка вкладки, `OneToOneField(UserInfo, related_name="family_income_case")`.

- `status`: `staff_draft`, `revision`, `pending_review`, `approved`;
- `family_members_count`: обязательное положительное число;
- `family_members_description`: обязательный свободный текст о членах семьи и
  занятиях;
- `family_characteristics`: свободный текст;
- `low_income_recognized`: nullable boolean — ручное решение сотрудника, не
  результат автоматического правила;
- `created_at`, `updated_at`.

### `FamilyIncomeDocument`

Связь карточки с существующим `documents.Document`.

- `case`: `ForeignKey(FamilyIncomeCase)`;
- `document`: `OneToOneField(documents.Document)`;
- `category`: `family_characteristic`, `income`, `social_benefit`, `other`;
- `candidate_comment`: описание документа;
- `staff_comment`: служебный комментарий;
- `review_status`: `pending`, `approved`, `clarification`;
- `added_by`, `created_at`, `updated_at`.

Кандидатский комментарий обязателен для всех категорий. Для документов
характеристики семьи и иных документов обязателен также файл. Статус проверки
живёт в этой модели, а не в общем `Document`: это не меняет поведение
существующего раздела документов.

### `IncomeEvidence`

Одна доходная запись на `FamilyIncomeDocument` категории `income`.

- `family_income_document`: `OneToOneField(FamilyIncomeDocument)`;
- `year`: `ForeignKey(IncomeYear)`;
- `owner_name`: обязательный свободный текст;
- `gross_amount`, `net_amount`, `average_monthly_amount`: nullable
  `DecimalField`;
- `months_received`: nullable `PositiveSmallIntegerField`, от 1 до 12;
- `absence_reason`: причина отсутствия сумм;
- `staff_decision_comment`: комментарий сотрудника об учёте документа.

Год и владелец обязательны. Если все числовые значения пусты, обязательна
`absence_reason`. Поле `months_received` хранится справочно и в первой
итерации не участвует в расчётах.

### `SocialBenefitEvidence`

Одна запись на `FamilyIncomeDocument` категории `social_benefit`.

- `family_income_document`: `OneToOneField(FamilyIncomeDocument)`;
- `recipient_name`: обязательный свободный текст;
- `benefit_type`: `ForeignKey(SocialBenefitType)`;
- `other_benefit_name`: обязательно при выборе «другое».

### Справочники

`IncomeYear`: `year` (unique), `is_active`, `sort_order`. Начальные значения:
2025 и 2026.

`SocialBenefitType`: `name`, `is_other`, `is_active`, `sort_order`. Состав
стандартизированного списка заполняется после отдельного продуктового решения.

### `FamilyIncomeDecision`

Ручной итог сотрудника, уникальный по паре `(case, year)`.

- `case`: `ForeignKey(FamilyIncomeCase)`;
- `year`: `ForeignKey(IncomeYear)`;
- `amount_per_member`: nullable `DecimalField` — «Среднемесячный доход на
  члена семьи»;
- `comment`: обязательное пояснение при создании или изменении суммы;
- `is_low_income_recognized`: nullable boolean — при необходимости решение
  можно вести по конкретному году; иначе использовать значение карточки;
- `created_by`, `updated_by`, `created_at`, `updated_at`.

После изменения доходного документа staff-экран помечает ручной итог как
требующий проверки. Никакого автоматического перерасчёта не происходит.

### Инструкция и аудит

`FamilyIncomeInstruction`: `url`, `version`, `status` (`draft`, `published`,
`archived`), `published_at`, `updated_by`, `updated_at`. В каждый момент
времени публикуется ровно одна версия.

`FamilyIncomeAuditEvent`: `case`, `actor`, `action`, `target_model`,
`target_id`, `before` (JSON), `after` (JSON), `reason`, `created_at`.
Записи аудита неизменяемы. Их создаёт сервисный слой, поскольку Django-сигнал
не знает пользователя, совершившего действие.

## Валидация и бизнес-правила

- Состав семьи обязателен: число членов и текстовое описание.
- Документы характеристики семьи обязательны до отправки карточки на проверку.
- Документ о социальных выплатах обязателен до отправки карточки на проверку.
- Для ИП, самозанятых и неофициальных доходов допустимы произвольные
  документы и свободные пояснения.
- Сотрудник самостоятельно принимает решение, учитывать ли сведения при
  ручном определении результата.
- Кандидат после проверки документа не может его удалить. Удаление до
  проверки — мягкое; подтверждённый документ исключает только сотрудник с
  записью в аудите.
- Кандидат не видит `staff_comment`, решение сотрудника и денежный итог.
  В его сводке показываются лишь статус заполнения и статус проверки.

## URL и экраны

Префикс приложения: `/family-income/`.

Пользовательские URL:

- `GET /family-income/` — вкладка и опубликованная инструкция;
- `POST /family-income/` — сохранение состава и характеристики;
- `POST /family-income/documents/add/`;
- `POST /family-income/documents/<id>/delete/`;
- `POST /family-income/income/add/`, `.../<id>/edit/`, `.../<id>/delete/`;
- `POST /family-income/benefits/add/`, `.../<id>/edit/`, `.../<id>/delete/`;
- `POST /family-income/submit/`.

Staff URL под существующим префиксом `staff/`:

- `GET /staff/family-income/<user_id>/` — проверка карточки, документов,
  доходных сведений, ручных итогов и аудита;
- `POST /staff/family-income/<user_id>/case/`;
- `POST /staff/family-income/<user_id>/documents/<id>/review/`;
- `POST /staff/family-income/<user_id>/income/<id>/decision/`;
- `POST /staff/family-income/<user_id>/decisions/<year>/`;
- `POST /staff/family-income/<user_id>/status/`;
- `GET /staff/family-income/<user_id>/audit/`.

Нужны ссылка на вкладку в кандидатском интерфейсе после собеседования и пункт
«Семья и доход» в staff-навигации и профиле кандидата.

## Доступ

- Неавторизованный пользователь перенаправляется на вход.
- Кандидат видит только собственную карточку.
- Вкладка доступна кандидату при `UserInfo.selection_step == AFTER_INTERVIEW`.
- Кандидат редактирует данные только при `FamilyIncomeCase.status == revision`.
  Во всех других состояниях — read-only.
- Каждый пользователь с `is_staff` имеет полный доступ к данным, проверке,
  ручному итогу, справочникам и инструкции.
- Ограничения реализуются и в queryset, и в представлениях, а не только в UI.

## Миграционный и релизный план

1. Создать приложение `family_income` и включить его в `INSTALLED_APPS`.
2. Первой миграцией создать перечисленные модели, индексы и ограничение
   уникальности `(case, year)` для `FamilyIncomeDecision`.
3. Второй data migration создать `IncomeYear` для 2025 и 2026. Перечень
   социальных выплат загрузить отдельной миграцией после утверждения.
4. Добавить формы, views, URL, шаблоны, сервисный слой аудита и staff-экран.
5. Добавить тесты доступа, обязательности данных, запрета повторной привязки
   документа, блокировки удаления проверенного документа и аудита ручного
   решения.
6. Не изменять существующие миграции, `UserInfo`, `documents.Document` и
   `review_by_tutor.service_views.export_users_xlsx`.

Если в будущем потребуется экспорт вкладки, его следует добавить отдельным
листом или новой версией выгрузки: порядок и набор колонок нынешнего Excel
экспорта не менять.

## Открытые продуктовые решения

- Точный стандартизированный перечень социальных выплат.
- Типовые примеры документов о доходе для инструкции.
- Допустимые форматы и максимальный размер файлов.
- Текст и ссылка первой опубликованной инструкции.
- Нужно ли фиксировать статус малоимущей семьи на карточке в целом или
  отдельно по каждому году.
