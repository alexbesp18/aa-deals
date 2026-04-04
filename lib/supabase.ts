import "server-only";
import { createClient } from "@supabase/supabase-js";

export function getSupabase() {
  return createClient(
    process.env.SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { db: { schema: "aa_hotels" } }
  );
}
