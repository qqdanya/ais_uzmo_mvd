from django.db import migrations, models


def copy_existing_access_to_write(apps, schema_editor):
    UserProfile = apps.get_model("accounts", "UserProfile")
    for profile in UserProfile.objects.iterator():
        if profile.role == "operator":
            profile.writable_departments.set(profile.allowed_departments.all())
            profile.writable_organs.set(profile.allowed_organs.all())


def clear_write_access(apps, schema_editor):
    UserProfile = apps.get_model("accounts", "UserProfile")
    for profile in UserProfile.objects.iterator():
        profile.writable_departments.clear()
        profile.writable_organs.clear()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_trashdismissal")]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="writable_departments",
            field=models.ManyToManyField(blank=True, related_name="writable_profiles", to="directory.department"),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="writable_organs",
            field=models.ManyToManyField(blank=True, related_name="writable_profiles", to="directory.territorialorgan"),
        ),
        migrations.RunPython(copy_existing_access_to_write, clear_write_access),
    ]
