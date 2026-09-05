-- 132_scan_samples_public_beta.sql
--
-- STAGED — not applied; review + paste in the SQL editor.
--
-- Audit items: H2 (scan_samples / scan-photo INSERT still gated on the scanner
-- tester allowlist) + M4 (no per-user cap on scan-samples storage objects).
--
-- WHAT THIS CHANGES
--   1. scan_samples INSERT policy — drops the `is_scanner_tester() or
--      is_graded_admin()` clause; becomes owner-only (auth.uid() = user_id).
--      The admin branch was only ever AND-ed with the owner check for INSERT,
--      so an admin inserting their own rows is unchanged. Latest definition
--      being replaced: 98_scan_samples_tester_gating.sql:11-14.
--   2. scan_samples UPDATE policy — drops the tester clause; keeps "graded
--      admin OR owner" (was "admin OR (owner AND tester)"). Replaces 98:17-22.
--   3. storage.objects INSERT policy for bucket scan-samples — drops the
--      tester/admin clause (own folder only, as before) AND adds a rolling-24h
--      cap of 3000 objects per user: the 1000 rows/day migration 115 enforces
--      x the 3 objects the client writes per scan (rectified crop, _raw frame,
--      _strip filmstrip). Replaces 98:25-29. The 115 triggers cap ROWS; the
--      client uploads the three objects BEFORE the row insert (Index.html,
--      uploadSample), so without this a caller can loop storage.upload alone
--      and never touch the row cap.
--
-- WHY
--   The scanner has been a public beta since 2026-08-04 (canScan = true for
--   everyone, consent + opt-out in migration 114) and migration 115's header
--   reasons "with the allowlist gone" — yet no migration ever removed the
--   allowlist from the write policies. Two possibilities, both bad:
--     (a) 98 is live as written: every non-allowlisted user's uploads fail
--         silently (uploadSample swallows every error), so the consent notice
--         promises uploads that never happen and the flywheel gets nothing;
--     (b) the gate was dropped live (dashboard / MCP) without a migration, so
--         the repo no longer describes production RLS.
--   Either way this file makes the repo and the intent agree.
--
--   CLAUDE.md line 83 ("Migration 98's scan_samples RLS still uses them
--   server-side to decide who may read OTHER people's samples") is WRONG: 98
--   gates INSERT and UPDATE (and storage INSERT), never SELECT. The read policy
--   is 91_rls_initplan_perf.sql:92-93 (owner or graded admin) and does not
--   mention testers. Rewrite that sentence when this lands.
--
-- VERIFY FIRST / PRECONDITIONS
--   * Run supabase/diagnostics/public_release_live_checks.sql section 1 to see
--     the LIVE policies. If the tester clause is already gone, items 1-2 are a
--     no-op and only the storage cap (item 3) is new. Section 8b shows
--     empirically whether non-allowlisted accounts have any rows since 08-04.
--   * Migrations 86 (bucket + scan_samples_obj_select) and 98 (policy names)
--     applied. The cap's count subquery relies on scan_samples_obj_select
--     (86:52-55) letting a user SELECT their own folder — do not drop it.
--   * Nothing here touches the SELECT policies, the 115 triggers, the consent
--     table, or the bucket limits (2 MB / image/jpeg, 98:31-34).
--
-- AFTER THIS LANDS
--   is_scanner_tester() and public.scanner_testers are referenced by no policy
--   and no client code (the client probe was removed before launch). They are
--   deliberately NOT dropped here — a DROP is a human decision per the
--   CLAUDE.md migration ledger. Migration 134 narrows the function's EXECUTE
--   grant but keeps `authenticated` so applying 134 before 132 cannot break 98.
--
-- Idempotent: every policy is drop-if-exists + create.

-- 1. scan_samples INSERT: owner only.
drop policy if exists scan_samples_insert on public.scan_samples;
create policy scan_samples_insert on public.scan_samples
  for insert to authenticated
  with check ((select auth.uid()) = user_id);

-- 2. scan_samples UPDATE: graded admin OR owner.
drop policy if exists scan_samples_update on public.scan_samples;
create policy scan_samples_update on public.scan_samples
  for update to authenticated
  using ((select public.is_graded_admin()) or (select auth.uid()) = user_id)
  with check ((select public.is_graded_admin()) or (select auth.uid()) = user_id);

-- 3. storage INSERT: own folder + rolling-24h object cap.
--    The subquery runs as the caller, so RLS on storage.objects applies to it:
--    scan_samples_obj_select (86:52-55) exposes exactly the caller's own
--    folder, which is the set being counted. `name like '<uid>/%'` is the same
--    test as (storage.foldername(name))[1] = uid but can use the
--    name_prefix_search index; a uuid contains no LIKE metacharacters.
drop policy if exists scan_samples_obj_insert on storage.objects;
create policy scan_samples_obj_insert on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'scan-samples'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and (
      select count(*)
        from storage.objects o
       where o.bucket_id = 'scan-samples'
         and o.name like ((select auth.uid())::text || '/%')
         and o.created_at >= now() - interval '24 hours'
    ) < 3000
  );

notify pgrst, 'reload schema';
