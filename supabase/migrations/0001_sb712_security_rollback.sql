drop publication if exists sb712_realtime;
drop policy if exists "sb712_audit_log_actor_read" on public.sb712_audit_log;
drop policy if exists "sb712_audit_log_service_write" on public.sb712_audit_log;
drop policy if exists "sb712_trust_ledger_read" on public.sb712_trust_ledger;
drop policy if exists "sb712_trust_ledger_admin_write" on public.sb712_trust_ledger;
drop policy if exists "sb712_schema_versions_service_only" on public.sb712_schema_versions;
drop table if exists public.sb712_audit_log;
drop table if exists public.sb712_trust_ledger;
drop table if exists public.sb712_schema_versions;
