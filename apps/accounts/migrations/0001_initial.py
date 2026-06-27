import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("directory", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("admin", "Администратор"), ("operator", "Оператор"), ("observer", "Наблюдатель")], default="observer", max_length=20)),
                ("allowed_organs", models.ManyToManyField(blank=True, related_name="allowed_profiles", to="directory.territorialorgan")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Профиль пользователя", "verbose_name_plural": "Профили пользователей"},
        )
    ]
