from django.db import migrations

SQL = (
    "CREATE TRIGGER identity_immutable BEFORE UPDATE OR DELETE ON suppliers_supplier "
    "FOR EACH ROW EXECUTE FUNCTION oq_immutable();"
)
REVERSE = "DROP TRIGGER identity_immutable ON suppliers_supplier;"


class Migration(migrations.Migration):
    dependencies = [("suppliers", "0001_initial"), ("core", "0002_history_guards")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
