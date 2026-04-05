"use server";

import { revalidatePath } from "next/cache";
import { getSupabase } from "@/lib/supabase";

export async function markAsBooked(formData: FormData) {
  const id = Number(formData.get("id"));
  if (!Number.isInteger(id) || id <= 0) return;

  const supabase = getSupabase();
  await supabase.from("deals").update({ is_booked: true }).eq("id", id);
  revalidatePath("/");
}
