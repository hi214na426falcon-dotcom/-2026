-- =====================================================================
-- Whimo Web — Supabase schema (run once in the SQL Editor)
-- Tables + Row Level Security (RLS) + Storage policies.
-- Safe to re-run: uses IF NOT EXISTS / CREATE OR REPLACE / DROP POLICY IF EXISTS.
-- =====================================================================
create extension if not exists pgcrypto;

-- ---------- Tables ----------
create table if not exists public.lists (
  id          uuid primary key default gen_random_uuid(),
  owner       uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name        text not null,
  description text not null default '',
  created_at  timestamptz not null default now()
);

create table if not exists public.list_members (
  list_id    uuid not null references public.lists(id) on delete cascade,
  email      text not null,
  role       text not null default 'editor',   -- 'editor' | 'viewer'
  invited_by uuid default auth.uid(),
  created_at timestamptz not null default now(),
  primary key (list_id, email)
);

create table if not exists public.spots (
  id         uuid primary key default gen_random_uuid(),
  list_id    uuid not null references public.lists(id) on delete cascade,
  name       text not null,
  category   text not null default 'other',
  memo       text not null default '',
  lat        double precision,
  lng        double precision,
  address    text not null default '',
  source_url text not null default '',
  visited    boolean not null default false,
  created_by uuid default auth.uid(),
  created_at timestamptz not null default now()
);

create table if not exists public.spot_photos (
  id         uuid primary key default gen_random_uuid(),
  spot_id    uuid not null references public.spots(id) on delete cascade,
  list_id    uuid not null references public.lists(id) on delete cascade,
  path       text not null,                    -- Storage path in bucket 'whimo'
  created_by uuid default auth.uid(),
  created_at timestamptz not null default now()
);

-- Hidden feature: receipts & amount spent
create table if not exists public.expenses (
  id           uuid primary key default gen_random_uuid(),
  list_id      uuid not null references public.lists(id) on delete cascade,
  spot_id      uuid references public.spots(id) on delete set null,
  amount       integer not null default 0,     -- JPY
  memo         text not null default '',
  spent_at     date not null default current_date,
  receipt_path text,                            -- Storage path (private to uploader)
  visibility   text not null default 'private', -- 'private' | 'shared'
  created_by   uuid not null default auth.uid(),
  created_at   timestamptz not null default now()
);

create index if not exists spots_list_idx        on public.spots(list_id);
create index if not exists members_email_idx      on public.list_members(lower(email));
create index if not exists photos_spot_idx        on public.spot_photos(spot_id);
create index if not exists expenses_list_idx      on public.expenses(list_id);
create index if not exists expenses_creator_idx   on public.expenses(created_by);

-- ---------- Helper functions (SECURITY DEFINER avoids RLS recursion) ----------
create or replace function public.current_email()
returns text language sql stable as $$
  select nullif(lower(auth.jwt() ->> 'email'), '')
$$;

create or replace function public.can_access_list(l uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from lists where id = l and owner = auth.uid())
      or exists (select 1 from list_members m
                 where m.list_id = l and lower(m.email) = public.current_email())
$$;

create or replace function public.can_edit_list(l uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from lists where id = l and owner = auth.uid())
      or exists (select 1 from list_members m
                 where m.list_id = l and lower(m.email) = public.current_email()
                       and m.role = 'editor')
$$;

create or replace function public.is_list_owner(l uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from lists where id = l and owner = auth.uid())
$$;

-- ---------- Enable RLS ----------
alter table public.lists         enable row level security;
alter table public.list_members  enable row level security;
alter table public.spots         enable row level security;
alter table public.spot_photos   enable row level security;
alter table public.expenses      enable row level security;

-- ---------- Policies: lists ----------
drop policy if exists lists_select on public.lists;
create policy lists_select on public.lists for select
  using (public.can_access_list(id));
drop policy if exists lists_insert on public.lists;
create policy lists_insert on public.lists for insert
  with check (owner = auth.uid());
drop policy if exists lists_update on public.lists;
create policy lists_update on public.lists for update
  using (owner = auth.uid()) with check (owner = auth.uid());
drop policy if exists lists_delete on public.lists;
create policy lists_delete on public.lists for delete
  using (owner = auth.uid());

-- ---------- Policies: list_members ----------
drop policy if exists members_select on public.list_members;
create policy members_select on public.list_members for select
  using (public.can_access_list(list_id));
drop policy if exists members_insert on public.list_members;
create policy members_insert on public.list_members for insert
  with check (public.is_list_owner(list_id));
drop policy if exists members_update on public.list_members;
create policy members_update on public.list_members for update
  using (public.is_list_owner(list_id));
drop policy if exists members_delete on public.list_members;
create policy members_delete on public.list_members for delete
  using (public.is_list_owner(list_id));

-- ---------- Policies: spots ----------
drop policy if exists spots_select on public.spots;
create policy spots_select on public.spots for select
  using (public.can_access_list(list_id));
drop policy if exists spots_cud on public.spots;
create policy spots_insert on public.spots for insert
  with check (public.can_edit_list(list_id));
drop policy if exists spots_update on public.spots;
create policy spots_update on public.spots for update
  using (public.can_edit_list(list_id)) with check (public.can_edit_list(list_id));
drop policy if exists spots_delete on public.spots;
create policy spots_delete on public.spots for delete
  using (public.can_edit_list(list_id));

-- ---------- Policies: spot_photos ----------
drop policy if exists photos_select on public.spot_photos;
create policy photos_select on public.spot_photos for select
  using (public.can_access_list(list_id));
drop policy if exists photos_insert on public.spot_photos;
create policy photos_insert on public.spot_photos for insert
  with check (public.can_edit_list(list_id));
drop policy if exists photos_delete on public.spot_photos;
create policy photos_delete on public.spot_photos for delete
  using (public.can_edit_list(list_id) or created_by = auth.uid());

-- ---------- Policies: expenses (visibility aware) ----------
-- private -> only the creator can read; shared -> anyone who can access the list.
drop policy if exists expenses_select on public.expenses;
create policy expenses_select on public.expenses for select
  using (created_by = auth.uid()
         or (visibility = 'shared' and public.can_access_list(list_id)));
drop policy if exists expenses_insert on public.expenses;
create policy expenses_insert on public.expenses for insert
  with check (created_by = auth.uid() and public.can_access_list(list_id));
drop policy if exists expenses_update on public.expenses;
create policy expenses_update on public.expenses for update
  using (created_by = auth.uid()) with check (created_by = auth.uid());
drop policy if exists expenses_delete on public.expenses;
create policy expenses_delete on public.expenses for delete
  using (created_by = auth.uid());

-- =====================================================================
-- Storage: private bucket 'whimo' for photos & receipts.
-- Path convention:
--   photos/<list_id>/<spot_id>/<uuid>.<ext>   (visible to list members)
--   receipts/<uploader_uid>/<uuid>.<ext>      (visible only to uploader)
-- =====================================================================
insert into storage.buckets (id, name, public)
values ('whimo', 'whimo', false)
on conflict (id) do nothing;

-- Spot photos: readable by anyone who can access the list.
drop policy if exists whimo_photos_read on storage.objects;
create policy whimo_photos_read on storage.objects for select
  using (bucket_id = 'whimo'
         and (storage.foldername(name))[1] = 'photos'
         and public.can_access_list( ((storage.foldername(name))[2])::uuid ));

drop policy if exists whimo_photos_write on storage.objects;
create policy whimo_photos_write on storage.objects for insert
  with check (bucket_id = 'whimo'
              and (storage.foldername(name))[1] = 'photos'
              and public.can_edit_list( ((storage.foldername(name))[2])::uuid ));

drop policy if exists whimo_photos_delete on storage.objects;
create policy whimo_photos_delete on storage.objects for delete
  using (bucket_id = 'whimo'
         and (storage.foldername(name))[1] = 'photos'
         and (public.can_edit_list( ((storage.foldername(name))[2])::uuid ) or owner = auth.uid()));

-- Receipts: private to the uploader only (protects the "hidden" money log).
drop policy if exists whimo_receipts_all on storage.objects;
create policy whimo_receipts_all on storage.objects for all
  using (bucket_id = 'whimo'
         and (storage.foldername(name))[1] = 'receipts'
         and owner = auth.uid())
  with check (bucket_id = 'whimo'
         and (storage.foldername(name))[1] = 'receipts'
         and owner = auth.uid());

-- =====================================================================
-- Trips (route recording) — optional cloud sync & album sharing.
-- =====================================================================
create table if not exists public.trips (
  id         uuid primary key default gen_random_uuid(),
  owner      uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name       text not null default '旅の記録',
  mode       text not null default 'live',
  started_at timestamptz,
  ended_at   timestamptz,
  distance   integer not null default 0,
  track      jsonb not null default '[]',
  spend      jsonb not null default '[]',
  created_at timestamptz not null default now()
);
create table if not exists public.trip_members (
  trip_id    uuid not null references public.trips(id) on delete cascade,
  email      text not null,
  role       text not null default 'viewer',
  created_at timestamptz not null default now(),
  primary key (trip_id, email)
);
create table if not exists public.trip_photos (
  id         uuid primary key default gen_random_uuid(),
  trip_id    uuid not null references public.trips(id) on delete cascade,
  path       text not null,
  lat        double precision,
  lng        double precision,
  at         timestamptz,
  caption    text not null default '',
  created_by uuid default auth.uid(),
  created_at timestamptz not null default now()
);
create index if not exists trip_photos_trip_idx on public.trip_photos(trip_id);
create index if not exists trip_members_email_idx on public.trip_members(lower(email));

create or replace function public.can_access_trip(tr uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from trips where id = tr and owner = auth.uid())
      or exists (select 1 from trip_members m where m.trip_id = tr and lower(m.email) = public.current_email())
$$;
create or replace function public.is_trip_owner(tr uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from trips where id = tr and owner = auth.uid())
$$;

alter table public.trips        enable row level security;
alter table public.trip_members enable row level security;
alter table public.trip_photos  enable row level security;

drop policy if exists trips_select on public.trips;
create policy trips_select on public.trips for select using (public.can_access_trip(id));
drop policy if exists trips_insert on public.trips;
create policy trips_insert on public.trips for insert with check (owner = auth.uid());
drop policy if exists trips_update on public.trips;
create policy trips_update on public.trips for update using (owner = auth.uid()) with check (owner = auth.uid());
drop policy if exists trips_delete on public.trips;
create policy trips_delete on public.trips for delete using (owner = auth.uid());

drop policy if exists trip_members_select on public.trip_members;
create policy trip_members_select on public.trip_members for select using (public.can_access_trip(trip_id));
drop policy if exists trip_members_ins on public.trip_members;
create policy trip_members_ins on public.trip_members for insert with check (public.is_trip_owner(trip_id));
drop policy if exists trip_members_del on public.trip_members;
create policy trip_members_del on public.trip_members for delete using (public.is_trip_owner(trip_id));

drop policy if exists trip_photos_select on public.trip_photos;
create policy trip_photos_select on public.trip_photos for select using (public.can_access_trip(trip_id));
drop policy if exists trip_photos_ins on public.trip_photos;
create policy trip_photos_ins on public.trip_photos for insert with check (public.is_trip_owner(trip_id));
drop policy if exists trip_photos_del on public.trip_photos;
create policy trip_photos_del on public.trip_photos for delete using (public.is_trip_owner(trip_id) or created_by = auth.uid());

-- Storage: trip photos under trips/<trip_id>/... readable by trip members.
drop policy if exists whimo_trips_read on storage.objects;
create policy whimo_trips_read on storage.objects for select
  using (bucket_id = 'whimo' and (storage.foldername(name))[1] = 'trips'
         and public.can_access_trip( ((storage.foldername(name))[2])::uuid ));
drop policy if exists whimo_trips_write on storage.objects;
create policy whimo_trips_write on storage.objects for insert
  with check (bucket_id = 'whimo' and (storage.foldername(name))[1] = 'trips'
              and public.is_trip_owner( ((storage.foldername(name))[2])::uuid ));
drop policy if exists whimo_trips_delete on storage.objects;
create policy whimo_trips_delete on storage.objects for delete
  using (bucket_id = 'whimo' and (storage.foldername(name))[1] = 'trips'
         and public.is_trip_owner( ((storage.foldername(name))[2])::uuid ));
