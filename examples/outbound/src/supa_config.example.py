"""Supabase config for the adapter fan-out gate (Example B).

Copy to supa_config.py (gitignored) and fill in a DISPOSABLE free-tier
project. The anon key is public-by-design, but the gate's test policy
grants anon writes — never point this at a project holding real data.

Dashboard SQL editor, run once:

    create table if not exists items (id uuid primary key, title text);
    alter table items enable row level security;
    create policy "anon all" on items
        for all to anon using (true) with check (true);
    create or replace function delete_item(item_id uuid) returns void
        language sql security definer as
        $$ delete from items where id = item_id $$;
"""

SUPA_URL = "https://<project-ref>.supabase.co"
SUPA_ANON_KEY = "<anon key from Project Settings -> API>"
