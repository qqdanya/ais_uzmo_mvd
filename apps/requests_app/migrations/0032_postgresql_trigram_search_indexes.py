from django.db import migrations


TRIGRAM_INDEXES = (
    ("rq_tmc_num_trgm", "requests_app_tmcrequest", "request_number"),
    ("rq_tmc_comment_trgm", "requests_app_tmcrequest", "comment"),
    ("rq_vrepair_num_trgm", "requests_app_vehiclerepairrequest", "request_number"),
    ("rq_vrepair_comment_trgm", "requests_app_vehiclerepairrequest", "comment"),
    ("rq_vfuel_num_trgm", "requests_app_vehiclefuelrequest", "request_number"),
    ("rq_vfuel_comment_trgm", "requests_app_vehiclefuelrequest", "comment"),
    ("rq_fire_num_trgm", "requests_app_firedepartmentrequest", "request_number"),
    ("rq_fire_comment_trgm", "requests_app_firedepartmentrequest", "comment"),
    ("rq_build_num_trgm", "requests_app_buildingrepairrequest", "request_number"),
    ("rq_build_comment_trgm", "requests_app_buildingrepairrequest", "comment"),
    ("rq_anti_num_trgm", "requests_app_antiterrormeasure", "request_number"),
    ("rq_anti_comment_trgm", "requests_app_antiterrormeasure", "comment"),
    ("rq_citsizi_num_trgm", "requests_app_citsiziequipment", "request_number"),
    ("rq_citsizi_comment_trgm", "requests_app_citsiziequipment", "comment"),
    ("rq_product_name_trgm", "requests_app_tmcproduct", "name"),
    ("dir_organ_name_trgm", "directory_territorialorgan", "name"),
    ("dir_folder_name_trgm", "directory_territorialorganphotofolder", "name"),
    ("dir_photo_file_trgm", "directory_territorialorganphoto", "original_filename"),
    ("dir_photo_desc_trgm", "directory_territorialorganphoto", "description"),
    ("auth_user_username_trgm", "auth_user", "username"),
    ("auth_user_first_trgm", "auth_user", "first_name"),
    ("auth_user_last_trgm", "auth_user", "last_name"),
    ("acct_profile_middle_trgm", "accounts_userprofile", "middle_name"),
    ("audit_object_repr_trgm", "audit_auditlog", "object_repr"),
)


def create_postgresql_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.quote_name
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in TRIGRAM_INDEXES:
        schema_editor.execute(
            f"CREATE INDEX IF NOT EXISTS {quote(name)} ON {quote(table)} "
            f"USING gin ({quote(column)} gin_trgm_ops)"
        )


def drop_postgresql_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.quote_name
    for name, _, _ in reversed(TRIGRAM_INDEXES):
        schema_editor.execute(f"DROP INDEX IF EXISTS {quote(name)}")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_alter_activationattempt_attempted_at_and_more"),
        ("audit", "0002_auditlog_audit_audit_territo_b41ede_idx_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("directory", "0010_territorialorganphoto_thumbnails"),
        ("requests_app", "0031_remove_antiterrormeasure_requests_ap_territo_7898fa_idx_and_more"),
    ]

    operations = [migrations.RunPython(create_postgresql_indexes, drop_postgresql_indexes)]
