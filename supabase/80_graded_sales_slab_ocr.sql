-- Persist the raw OCR text of each graded-slab label on the sale row, so we never
-- re-download + re-OCR the same image and so the label text is a reusable reference
-- (printing/variant classification, grade audits, manual review). The slab-OCR
-- scripts (ocr_slab_audit.py, classify_c1_printing.py) write these when they read an
-- image; the daily pipeline will populate them going forward.
alter table public.graded_sales add column if not exists slab_ocr text;
alter table public.graded_sales add column if not exists slab_ocr_at timestamptz;
comment on column public.graded_sales.slab_ocr is
  'Raw OCR text of the graded-slab label strip. Persisted so we never re-OCR the same image + as a manual-review reference.';
notify pgrst, 'reload schema';
