import re

from django.db import migrations


def normalize_product_name(value):
    value = (value or "").replace("ё", "е").replace("Ё", "Е").casefold()
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def clean_product_name(value):
    return " ".join((value or "").split())


def populate_tmc_products(apps, schema_editor):
    TmcProduct = apps.get_model("requests_app", "TmcProduct")
    TmcRequestItem = apps.get_model("requests_app", "TmcRequestItem")
    products_by_normalized_name = {
        product.normalized_name: product
        for product in TmcProduct.objects.all()
    }
    for item in TmcRequestItem.objects.filter(product__isnull=True).iterator():
        name = clean_product_name(item.name)
        if not name:
            continue
        normalized_name = normalize_product_name(name)
        product = products_by_normalized_name.get(normalized_name)
        if not product:
            product = TmcProduct.objects.create(
                name=name,
                normalized_name=normalized_name,
                unit=clean_product_name(item.unit) or "шт.",
            )
            products_by_normalized_name[normalized_name] = product
        item.product = product
        item.name = product.name
        item.save(update_fields=["product", "name"])


class Migration(migrations.Migration):

    dependencies = [
        ("requests_app", "0020_tmcproduct_tmcrequestitem_product"),
    ]

    operations = [
        migrations.RunPython(populate_tmc_products, migrations.RunPython.noop),
    ]
