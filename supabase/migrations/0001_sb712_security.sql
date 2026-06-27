-- SB-712 security + trust bootstrap
create extension if not exists pgcrypto;

create table if not exists public.sb712_audit_log (
    id uuid primary key default gen_random_uuid(),
    actor_id uuid references auth.users(id),
    trace_id uuid not null default gen_random_uuid(),
    action text not null,
    resource text not null,
    status text not null,
    payload_ciphertext bytea not null,
    payload_nonce bytea not null,
    payload_key_id integer not null default 0,
    previous_hash text not null,
    entry_hash text not null unique,
    merkle_root text not null,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.sb712_trust_ledger (
    id uuid primary key default gen_random_uuid(),
    trace_id uuid not null,
    operation_name text not null,
    verification_count integer not null check (verification_count >= 3),
    verification_proof jsonb not null,
    immutable_root text not null,
    trusted boolean not null default false,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.sb712_schema_versions (
    version text primary key,
    rollback_version text not null,
    rollback_sql text not null,
    applied_at timestamptz not null default timezone('utc', now())
);

alter table public.sb712_audit_log enable row level security;
alter table public.sb712_trust_ledger enable row level security;
alter table public.sb712_schema_versions enable row level security;

create policy "sb712_audit_log_actor_read"
    on public.sb712_audit_log
    for select
    to authenticated
    using (actor_id = auth.uid() or auth.role() = 'service_role');

create policy "sb712_audit_log_service_write"
    on public.sb712_audit_log
    for insert
    to authenticated
    with check (actor_id = auth.uid() or auth.role() = 'service_role');

create policy "sb712_trust_ledger_read"
    on public.sb712_trust_ledger
    for select
    to authenticated
    using (true);

create policy "sb712_trust_ledger_admin_write"
    on public.sb712_trust_ledger
    for all
    to authenticated
    using (coalesce(auth.jwt() ->> 'role', '') = 'admin' or auth.role() = 'service_role')
    with check (coalesce(auth.jwt() ->> 'role', '') = 'admin' or auth.role() = 'service_role');

create policy "sb712_schema_versions_service_only"
    on public.sb712_schema_versions
    for all
    to authenticated
    using (auth.role() = 'service_role')
    with check (auth.role() = 'service_role');

drop publication if exists sb712_realtime;
create publication sb712_realtime
    for table public.sb712_audit_log, public.sb712_trust_ledger;

insert into public.sb712_schema_versions (version, rollback_version, rollback_sql)
values ('0001_sb712_security', '0000', '0001_sb712_security_rollback.sql')
on conflict (version) do nothing;
