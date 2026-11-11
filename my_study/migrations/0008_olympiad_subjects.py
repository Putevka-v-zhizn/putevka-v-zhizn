from django.db import migrations, models


def move_olympiad_courses(apps, schema_editor):
    Subject = apps.get_model("my_study", "Subject")
    Course = apps.get_model("my_study", "Course")
    alias = schema_editor.connection.alias
    subject_ids = list(Course.objects.using(alias).filter(is_olympiad=True).values_list("subject_id", flat=True).distinct())
    for subject in Subject.objects.using(alias).filter(pk__in=subject_ids):
        # Keep ordinary courses, exam plans and results on their original subject.
        base_name = f"Олимпиадная подготовка — {subject.name}"
        name = base_name[:100]
        index = 2
        while Subject.objects.using(alias).filter(name=name).exists():
            suffix = f" ({index})"
            name = base_name[:100 - len(suffix)] + suffix
            index += 1
        base_slug = f"olympiad-{subject.pk}"
        slug = base_slug
        index = 2
        while Subject.objects.using(alias).filter(slug=slug).exists():
            slug = f"{base_slug}-{index}"
            index += 1
        olympiad_subject = Subject.objects.using(alias).create(name=name, slug=slug, is_olympiad=True)
        Course.objects.using(alias).filter(subject_id=subject.pk, is_olympiad=True).update(subject_id=olympiad_subject.pk)


def restore_course_flags(apps, schema_editor):
    Course = apps.get_model("my_study", "Course")
    Course.objects.using(schema_editor.connection.alias).filter(subject__is_olympiad=True).update(is_olympiad=True)


class Migration(migrations.Migration):
    dependencies = [("my_study", "0007_courseduration_course_is_olympiad_course_duration")]
    operations = [
        migrations.AddField(model_name="subject", name="is_olympiad", field=models.BooleanField("Олимпиадный предмет", default=False)),
        migrations.RunPython(move_olympiad_courses, restore_course_flags),
    ]
