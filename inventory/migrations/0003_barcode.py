from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_product_image"),
    ]

    operations = [
        migrations.CreateModel(
            name="BarcodeSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("next_value", models.PositiveIntegerField(default=1)),
            ],
        ),
        migrations.AddField(
            model_name="product",
            name="barcode",
            field=models.CharField(default="", max_length=13, unique=True),
            preserve_default=False,
        ),
    ]
