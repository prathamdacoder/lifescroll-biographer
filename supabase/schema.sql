-- Lifescroll schema for Supabase (run in the SQL editor).
-- Supabase Auth owns auth.users; this mirrors biographies for cross-device access.

create table if not exists public.biographies (
  id uuid primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  title text default 'Untitled Life',
  subtitle text default '',
  status text not null default 'queued',
  progress real default 0,
  stage text default '',
  transcript text,
  book jsonb default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists biographies_user_idx on public.biographies (user_id, created_at desc);

alter table public.biographies enable row level security;

drop policy if exists "own rows: select" on public.biographies;
create policy "own rows: select" on public.biographies
  for select using (auth.uid() = user_id);

drop policy if exists "own rows: insert" on public.biographies;
create policy "own rows: insert" on public.biographies
  for insert with check (auth.uid() = user_id);

drop policy if exists "own rows: update" on public.biographies;
create policy "own rows: update" on public.biographies
  for update using (auth.uid() = user_id);

drop policy if exists "own rows: delete" on public.biographies;
create policy "own rows: delete" on public.biographies
  for delete using (auth.uid() = user_id);

-- The API writes with the service-role key, which bypasses RLS by design.
