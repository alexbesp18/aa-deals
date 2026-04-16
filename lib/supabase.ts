import "server-only";
import { createClient } from "@supabase/supabase-js";

export type Schema = "aa_hotels" | "aa_tools";

export function getSupabase(schema: Schema = "aa_hotels") {
  return createClient(
    process.env.SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { db: { schema } }
  );
}
