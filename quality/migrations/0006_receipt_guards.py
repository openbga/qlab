from django.db import migrations

SQL = """
CREATE TRIGGER lot_receipt_immutable BEFORE UPDATE OR DELETE ON quality_lotreceipt
FOR EACH ROW EXECUTE FUNCTION oq_immutable();
CREATE FUNCTION quality_guard_receipt_insert() RETURNS trigger AS $$
DECLARE
  lot_state text;
BEGIN
  -- FOR SHARE waits for a disposition that is updating the lot, then reads the state it
  -- committed, so a receipt row cannot slip in beside a release.
  SELECT state INTO lot_state FROM quality_lot WHERE id = NEW.lot_id FOR SHARE;
  IF lot_state IS DISTINCT FROM 'quarantine' THEN
    RAISE EXCEPTION 'Receipt details are recorded only while the lot is in quarantine';
  END IF;
  IF NEW.corrects_id IS NOT NULL AND
     (SELECT lot_id FROM quality_lotreceipt WHERE id = NEW.corrects_id)
       IS DISTINCT FROM NEW.lot_id THEN
    RAISE EXCEPTION 'A receipt correction belongs to the lot of the record it corrects';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER lot_receipt_insert_guard BEFORE INSERT ON quality_lotreceipt
FOR EACH ROW EXECUTE FUNCTION quality_guard_receipt_insert();
"""
REVERSE = """
DROP TRIGGER lot_receipt_insert_guard ON quality_lotreceipt;
DROP FUNCTION quality_guard_receipt_insert();
DROP TRIGGER lot_receipt_immutable ON quality_lotreceipt;
"""


class Migration(migrations.Migration):
    dependencies = [("quality", "0005_lotreceipt"), ("core", "0002_history_guards")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
