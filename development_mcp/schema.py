"""Explicit column allowlists. Internal columns are never serialized to clients.

Changes here require review of both output and PostgreSQL column grants.
"""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
import os
import sys
from collections import deque


@dataclass(frozen=True)
class Load:
    """Load this table where column matches source.source_column in this case.

    None means every direction; a tuple restricts the rule to those directions.
    A conventional foreign key to source.id also becomes an opaque response link.
    """

    source: str
    column: str
    source_column: str = "id"
    programs: tuple[str, ...] | None = None

    def applies(self, program):
        return self.programs is None or program in self.programs


@dataclass(frozen=True)
class CaseFilter:
    name: str
    kind: str  # text presence, numeric maximum, related-record count, or choice
    field: str | None = None
    choices: tuple[str, ...] = ()
    programs: tuple[str, ...] | None = None
    description: str = ""

    def applies(self, program):
        return self.programs is None or program in self.programs


@dataclass(frozen=True)
class Table:
    output: tuple[str, ...] = ()
    internal: tuple[str, ...] = ()
    # (column, replacement category); used only to clean other fields.
    identities: tuple[tuple[str, str], ...] = ()
    loads: tuple[Load, ...] = ()
    links: tuple[tuple[str, str], ...] = ()
    age_field: str | None = None
    filters: tuple[CaseFilter, ...] = ()

    @property
    def references(self):
        automatic = {load.column: load.source for load in self.loads
                     if load.source_column == "id" and load.column != "id"}
        return automatic | dict(self.links)

    @property
    def columns(self):
        return tuple(dict.fromkeys(("id",) + self.output + self.internal
                                   + tuple(k for k, _ in self.identities)
                                   + tuple(load.column for load in self.loads)
                                   + tuple(self.references)
                                   + ((self.age_field,) if self.age_field else ())))


def words(value):
    return tuple(value.split())


TABLES = {
    "auth_user": Table(internal=(), identities=(("first_name", "participant"), ("last_name", "participant"), ("email", "contact"), ("username", "contact")),
        loads=(Load('scholar_form_userinfo', 'id', source_column='user_id'), Load('nto_travel_ntoapplication', 'id', source_column='user_id', programs=('nto',)),)),
    "scholar_form_userinfo": Table(
        output=words("""selection_step form_status status gender revision_comment next_year_class_digit
            class_profile subject_grades olympiad_plans admission_path target_universities specializations
            mother father legal_guardian siblings_count siblings_info family_size income_per_member
            is_low_income receives_subsidy other_factors has_pc_with_internet achievements preparation_plan
            foundation_help heard_about_program willing_to_participate after_interview_parents_notified
            after_interview_documents_ready tutor_summary avg_grade_last_period family_material_status
            internal_study_profile is_large_family is_single_parent_family has_candidate_disability
            is_orphan_or_under_guardianship has_breadwinner_loss has_relative_disability is_parent_pensioner
            is_parent_in_svo has_alumni_sibling settlement_type life_situation_notes"""),
        internal=("user_id", "birth_date"),
        identities=(("first_name", "participant"), ("last_name", "participant"), ("middle_name", "participant"),
                    ("phone", "contact"), ("email", "contact"), ("vk", "contact"),
                    ("region", "place"), ("city", "place"), ("address", "address"),
                    ("school_name", "organization"), ("school_address", "address"), ("class_teacher", "person")),
        loads=(Load('auth_user', 'user_id', programs=('nto',)), Load('family_income_familyincomecase', 'id', source_column='user_info_id', programs=('family_income',)),),
        age_field="birth_date",
        filters=(CaseFilter("selection_step", "choice", "selection_step", choices=("form", "test", "ml", "video", "interview_prep", "after_interview"), programs=("main",), description="Current selection stage"),)),
    "scholar_form_userpersonaldata": Table(internal=("user_id",), identities=tuple(
        (field, category) for category, fields in (
            ("participant", "first_name last_name middle_name"),
            ("document", "passport_series passport_number passport_department_code snils"),
            ("address", "registration_address"), ("organization", "passport_issued_by bank_name"),
            ("bank", "bank_account bank_bik bank_correspondent_account"), ("contact", "phone email")
        ) for field in fields.split()),
        loads=(Load('auth_user', 'user_id'),)),
    "scholar_form_staffnote": Table(output=("text", "is_favorite"), internal=("target_user_id",),
        loads=(Load('auth_user', 'target_user_id'),),
        filters=(CaseFilter("staff_note_count", "count"),)),
    "core_motivationletter": Table(output=words("is_done letter_text is_favorite admin_score admin_rating revision_comment status"), internal=("user_id",),
        loads=(Load('auth_user', 'user_id', programs=('main',)),),
        filters=(CaseFilter("has_motivation_letter", "text", "letter_text"), CaseFilter("letter_status", "choice", "status", choices=("draft", "submitted", "revision")), CaseFilter("motivation_score", "number", "admin_score"),)),
    "core_motivationletterrubricreview": Table(output=words("""char_count word_count total_score specialty_choice_score
        university_choice_score current_preparation_score admission_trajectory_score next_year_preparation_score
        higher_education_value_score support_criticality_score composition_penalty style_penalty orthography_penalty
        syntax_penalty is_too_short score_capped_for_short_length suspected_ai_generated returned_for_revision
        reviewer_comment family hobbies achievements traits school_teachers prep_subjects specialty preferred_universities
        relocation olympiads motivation help_criticality extra justification"""), internal=("letter_id",),
        loads=(Load('core_motivationletter', 'letter_id', programs=('main',)),)),
    "scholar_form_scholarvideo": Table(output=words("""review score transcript_text transcript_status
        online_school_course online_school_prior_experience online_school_observations online_school_selected_courses
        online_school_choice_reason online_school_extra_help online_school_used_materials online_school_interview_questions
        schedule_school_day schedule_homework_time schedule_activities_time schedule_exam_prep_time schedule_rest_time
        schedule_weekend_day schedule_realistic_assessment schedule_extra_help schedule_used_materials schedule_interview_questions"""), internal=("user_id",),
        loads=(Load('auth_user', 'user_id', programs=('main',)),),
        filters=(CaseFilter("has_video_transcript", "text", "transcript_text"),)),
    "review_by_tutor_testassignment": Table(output=words("""title instructions status
        result_text passed revision_comment numeric_grade verbal_grade
        logical_grade numeric_percentile verbal_percentile logical_percentile"""), internal=("user_id",),
        loads=(Load('auth_user', 'user_id', programs=('main',)),),
        filters=(CaseFilter("test_count", "count"),)),
    "review_by_tutor_interview": Table(output=("notes", "transcript", "transcript_status"), internal=("user_id",),
        loads=(Load('auth_user', 'user_id', programs=('main',)),),
        filters=(CaseFilter("has_interview_transcript", "text", "transcript"),)),
    "review_by_tutor_interviewresult": Table(output=words("""status school_type school_distance_km school_distance_minutes
        school_specialization school_students_total school_left_after_9_est school_students_11 class_profile has_ege_teachers_all
        teach_quality_ru teach_quality_math teach_quality_phys teach_quality_chem teach_quality_bio teach_quality_inf
        teach_quality_geo teach_quality_soc teach_quality_lit teach_quality_hist teach_quality_lang triples_reason
        favorite_teacher favorite_subject has_computer_lab olympiads_frequency clubs_info olympiad_support_by_school
        other_school_notes aims_medal admission_way ege_subjects mock_ru mock_math_base mock_math_prof mock_phys mock_chem
        mock_bio mock_inf mock_geo mock_soc mock_lit mock_hist mock_lang target_ru target_math_base target_math_prof
        target_phys target_chem target_bio target_inf target_geo target_soc target_lit target_hist target_lang had_tutor
        tutor_details had_online_courses online_courses_details olympiad_experience olympiads_planned need_olympiad_prep
        specialties need_career_guidance universities need_university_help why_higher_education prep_9_10 prep_10_11
        ready_to_move discussed_with_parents other_support_needed family_structure family_many_children family_people_count
        siblings_info grandparents_info dependents_info has_disabled_need_care candidate_orphan candidate_disabled
        breadwinner_loss family_other_circumstances mother_job mother_has_he father_job father_has_he step_parent_job
        step_parent_has_he parents_self_employed_details other_relatives_jobs parent_on_pension_or_care why_parent_not_working
        alimony_paid benefits_received low_income_recognized family_other_notes parents_involved_in_study siblings_interfere_study
        household_load settlement_status distance_to_reg_center_km housing_type utilities own_room own_workdesk own_computer
        own_phone supports_whatsapp_telegram has_printer home_internet phone_internet family_has_car relatives_in_big_cities
        pets has_bank_card summer_holidays financial_notes weekday_routine weekend_routine clubs_hobbies volunteering gto_passed
        sport_info studies_extra_resources_frequency self_study_example other_resources reads_books_frequency favorite_book
        favorite_games favorite_movies favorite_socials friends_count_info friends_admission_discussion part_time_job other_achievements
        success_qualities success_definition unfinished_cases asks_for_help_how heard_about_fund parents_know_and_agree selection_experience
        knows_support_program most_useful_expected would_participate_without_stipend understands_group_courses knows_our_schools
        understands_homework_need plan_to_combine ready_regular_contact will_inform_if_absent preferred_contact_method
        ready_for_chats_webinars interesting_topics ready_additional_tests helpful_materials ready_tell_school ready_mentor_next
        fund_questions understands_next_steps other_notes interviewer_summary interviewer_risks interviewer_recommendations interviewer_score"""),
        internal=("interview_id",), identities=(("school_number", "organization"),),
        loads=(Load('review_by_tutor_interview', 'interview_id', programs=('main',)),),
        filters=(CaseFilter("interview_score", "number", "interviewer_score"),)),
    "nto_travel_ntoapplication": Table(output=words("""status school_class is_adult parent_role finalist_declared
        parent_contact_declared previous_final previous_payers possible_payers school_support parent_support ticket_cost
        income_disclosure income_per_member income_proof family_material_status circumstances circumstance_proof situation_details
        universities specializations achievements no_achievements olympiad_plans preparation_methods preparation_details nto_goal
        refused_olympiads refusal_reason admission_without_trip has_admission_advantages advantage_details free_thoughts public_comment internal_note"""),
        internal=("user_id", "campaign_id"), identities=(("first_name", "participant"), ("last_name", "participant"),
            ("middle_name", "participant"), ("parent_name", "person"), ("phone", "contact"), ("email", "contact"),
            ("telegram", "contact"), ("parent_phone", "contact"), ("region", "place"), ("city", "place"), ("final_city", "place")),
        loads=(Load('auth_user', 'user_id', programs=('main', 'family_income')),),
        links=(('campaign_id', 'nto_travel_ntocampaign'),),
        filters=(CaseFilter("has_situation_details", "text", "situation_details", programs=("nto",)),)),
    "nto_travel_ntocampaign": Table(output=("academic_year",),
        loads=(Load('nto_travel_ntoapplication', 'id', source_column='campaign_id', programs=('nto',)),)),
    "nto_travel_ntoapplicationreview": Table(output=("criticality", "criticality_reason", "motivation", "motivation_reason"), internal=("application_id",),
        loads=(Load('nto_travel_ntoapplication', 'application_id', programs=('nto',)),),
        filters=(CaseFilter("criticality", "number", "criticality"), CaseFilter("motivation_score", "number", "motivation"),)),
    "nto_travel_ntoapplicationprofile": Table(output=("rank", "name_snapshot"), internal=("application_id",), identities=(("city_snapshot", "place"),),
        loads=(Load('nto_travel_ntoapplication', 'application_id', programs=('nto',)),)),
    "nto_travel_ntoapplicationevent": Table(output=("action", "old_status", "new_status", "comment"), internal=("application_id",),
        loads=(Load('nto_travel_ntoapplication', 'application_id', programs=('nto',)),)),
    "family_income_familyincomecase": Table(output=words("status family_members_count family_members_description family_characteristics low_income_recognized revision_comment"), internal=("user_info_id",),
        links=(('user_info_id', 'scholar_form_userinfo'),),
        filters=(CaseFilter("family_size", "number", "family_members_count", programs=("family_income",)),)),
    "family_income_familyincomedocument": Table(output=("category", "candidate_comment", "staff_comment", "review_status"), internal=("case_id",),
        loads=(Load('family_income_familyincomecase', 'case_id', programs=('family_income',)),),
        filters=(CaseFilter("document_count", "count"),)),
    "family_income_incomeevidence": Table(output=words("gross_amount net_amount average_monthly_amount months_received absence_reason staff_decision_comment"), internal=("family_income_document_id", "year_id"), identities=(("owner_name", "person"),),
        loads=(Load('family_income_familyincomedocument', 'family_income_document_id', programs=('family_income',)),),
        links=(('year_id', 'family_income_incomeyear'),),
        filters=(CaseFilter("income_source_count", "count"),)),
    "family_income_socialbenefitevidence": Table(output=("benefit_description",), internal=("family_income_document_id",), identities=(("recipient_name", "person"),),
        loads=(Load('family_income_familyincomedocument', 'family_income_document_id', programs=('family_income',)),)),
    "family_income_familyincomedecision": Table(output=("amount_per_member", "comment", "is_low_income_recognized"), internal=("case_id", "year_id"),
        loads=(Load('family_income_familyincomecase', 'case_id', programs=('family_income',)),),
        links=(('year_id', 'family_income_incomeyear'),)),
    "family_income_incomeyear": Table(output=("year",),
        loads=(Load('family_income_incomeevidence', 'id', source_column='year_id', programs=('family_income',)), Load('family_income_familyincomedecision', 'id', source_column='year_id', programs=('family_income',)),)),
}

# Root identifiers are private database identifiers, never accepted from clients.
PROGRAMS = {
    "main": ("scholar_form_userinfo", "form_status", ("draft", "submitted", "revision", "clarification", "approved", "rejected")),
    "nto": ("nto_travel_ntoapplication", "status", ("draft", "submitted", "clarification", "approved", "rejected")),
    "family_income": ("family_income_familyincomecase", "status", ("staff_draft", "revision", "pending_review", "approved")),
}


def filter_path(program, target, tables=None, programs=None):
    """Shortest declared join path from a case root, without traversing cycles."""
    tables = TABLES if tables is None else tables
    programs = PROGRAMS if programs is None else programs
    root = programs[program][0]
    pending, seen = deque([(root, ())]), {root}
    while pending:
        source, path = pending.popleft()
        if source == target:
            return path
        for table, spec in tables.items():
            for load in spec.loads:
                if load.source == source and load.applies(program) and table not in seen:
                    seen.add(table)
                    pending.append((table, path + ((table, load),)))
    return None


def case_filters(program, tables=None, programs=None):
    tables = TABLES if tables is None else tables
    result = {}
    for table, spec in tables.items():
        for definition in spec.filters:
            if definition.applies(program) and filter_path(program, table, tables, programs) is not None:
                if definition.name in result:
                    raise ValueError("Duplicate case filter")
                result[definition.name] = (table, definition)
    return result


def validate_registry(tables=None, programs=None):
    """Catch incomplete declarations before serving data or generating grants."""
    tables = TABLES if tables is None else tables
    programs = PROGRAMS if programs is None else programs
    identifier = re.compile(r"[a-z_][a-z0-9_]*\Z")
    categories = {"participant", "person", "place", "organization", "contact", "document", "address", "bank"}
    for name, spec in tables.items():
        if not identifier.fullmatch(name) or any(not identifier.fullmatch(c) for c in spec.columns):
            raise ValueError("Invalid registry identifier")
        if len(set(spec.output)) != len(spec.output):
            raise ValueError("Duplicate output field")
        for column in spec.output:
            if column == "id" or column.endswith("_id") or re.search(r"(?:^|_)(?:password|token|error)(?:_|$)", column):
                raise ValueError("Unsafe output field")
        if set(spec.output) & ({c for c, _ in spec.identities} | set(spec.internal) | set(spec.references)):
            raise ValueError("Output and private fields must be separate")
        if any(kind not in categories for _, kind in spec.identities):
            raise ValueError("Unknown identity category")
        for definition in spec.filters:
            if not identifier.fullmatch(definition.name) or definition.kind not in {"text", "number", "count", "choice"}:
                raise ValueError("Invalid case filter")
            if definition.kind == "count":
                if definition.field is not None:
                    raise ValueError("Count filters cannot reference a field")
            elif definition.field not in spec.output:
                raise ValueError("Case filters can reference only public output fields")
            if definition.kind == "choice" and (not definition.choices or any(not isinstance(c, str) for c in definition.choices)):
                raise ValueError("Choice filters need explicit allowed values")
            if definition.programs is not None and (not definition.programs or not set(definition.programs) <= programs.keys()):
                raise ValueError("Unknown case filter direction")
        for load in spec.loads:
            if load.source not in tables or load.source_column not in tables[load.source].columns:
                raise ValueError("Unknown load source or source column")
            if load.programs is not None and (not load.programs or not set(load.programs) <= programs.keys()):
                raise ValueError("Unknown direction in load rule")
        for _, target in spec.links:
            if target not in tables:
                raise ValueError("Unknown link target")
        # Conflicting inferred references require an explicit override.
        inferred = {}
        for load in spec.loads:
            if load.source_column == "id" and load.column != "id":
                previous = inferred.setdefault(load.column, load.source)
                if previous != load.source and load.column not in dict(spec.links):
                    raise ValueError("Ambiguous reference")
    reachable_any = set()
    for name, (root, status_column, statuses) in programs.items():
        if not identifier.fullmatch(name) or root not in tables or status_column not in tables[root].output or not statuses:
            raise ValueError("Invalid direction")
        reachable = {root}
        while True:
            expanded = reachable | {table for table, spec in tables.items()
                                    if any(load.source in reachable and load.applies(name) for load in spec.loads)}
            if expanded == reachable:
                break
            reachable = expanded
        reachable_any |= reachable
        for table, spec in tables.items():
            if table not in reachable and any(f.programs is not None and name in f.programs for f in spec.filters):
                raise ValueError("Case filter direction cannot reach its table")
        case_filters(name, tables, programs)
    if reachable_any != tables.keys():
        raise ValueError("Registry contains an unreachable table")


def registry_version():
    definition = {"tables": {name: asdict(spec) for name, spec in TABLES.items()}, "programs": PROGRAMS}
    return hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()[:16]



def configure_programs(value):
    """Explicit deployment profile; never discover or expose new tables automatically."""
    if value is None:
        return
    names = tuple(item.strip() for item in value.split(',') if item.strip())
    if not names or len(set(names)) != len(names) or not set(names) <= PROGRAMS.keys():
        raise ValueError("Invalid MCP_PROGRAMS profile")
    # NTO is optional in the application; don't read its ancillary identity tables
    # when the program has not been deployed on this server.
    available = {name: spec for name, spec in TABLES.items() if 'nto' in names or not name.startswith('nto_travel_')}
    reachable = set()
    for program in names:
        found = {PROGRAMS[program][0]}
        while True:
            expanded = found | {name for name, spec in available.items()
                                if any(load.source in found and load.applies(program) for load in spec.loads)}
            if found == expanded:
                break
            found = expanded
        reachable |= found
    configured = {}
    for name, spec in available.items():
        if name not in reachable:
            continue
        loads = tuple(replace(load, programs=tuple(p for p in load.programs if p in names)) if load.programs else load
                      for load in spec.loads if load.source in reachable and (load.programs is None or set(load.programs) & set(names)))
        filters = tuple(replace(f, programs=tuple(p for p in f.programs if p in names)) if f.programs else f
                        for f in spec.filters if f.programs is None or set(f.programs) & set(names))
        configured[name] = replace(spec, loads=loads, filters=filters,
                                   links=tuple((column, target) for column, target in spec.links if target in reachable))
    TABLES.clear()
    TABLES.update(configured)
    for name in tuple(PROGRAMS):
        if name not in names:
            del PROGRAMS[name]

_profile = os.getenv('MCP_PROGRAMS')
_django_conf = sys.modules.get('django.conf')
if _profile is None and _django_conf is not None and _django_conf.settings.configured:
    if not any(name == 'nto_travel' or name.startswith('nto_travel.') for name in _django_conf.settings.INSTALLED_APPS):
        _profile = 'main,family_income'
configure_programs(_profile)
validate_registry()

if __name__ == "__main__":
    print(json.dumps({"code": "ok", "registry_version": registry_version(), "tables": len(TABLES), "programs": list(PROGRAMS)}))
