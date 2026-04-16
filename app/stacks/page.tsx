import { getSupabase } from "@/lib/supabase";

type Stack = {
  merchant_name: string;
  merchant_name_normalized: string;
  portal_rate: number;
  portal_is_elevated: boolean;
  portal_click_url: string | null;
  sm_type: string;
  sm_miles_amount: number;
  sm_lp_amount: number;
  sm_min_spend: number | null;
  sm_expires_at: string | null;
  sm_headline: string | null;
  sm_per_dollar: number;
  cc_rate: number;
  combined_yield: number;
  last_scraped_at: string;
};

function formatSmOffer(s: Stack) {
  if (s.sm_type === "flat_bonus" && s.sm_min_spend) {
    return `+${s.sm_miles_amount} mi on $${s.sm_min_spend}+`;
  }
  if (s.sm_type === "per_dollar") {
    return `+${s.sm_miles_amount} mi/$`;
  }
  return s.sm_headline?.slice(0, 60) || `+${s.sm_miles_amount} mi`;
}

function formatExpiry(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("T")[0]!.split("-").map(Number);
  const exp = new Date(y!, m! - 1, d!);
  const days = Math.ceil((exp.getTime() - Date.now()) / 86400000);
  if (days < 0) return "expired";
  if (days === 0) return "today";
  if (days <= 14) return `${days}d`;
  return exp.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatRelative(iso: string): string {
  const hours = Math.floor((Date.now() - new Date(iso).getTime()) / 3600000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export const dynamic = "force-dynamic";

export default async function StacksPage(props: {
  searchParams: Promise<{ min_yield?: string }>;
}) {
  const searchParams = await props.searchParams;
  const minYield = Number(searchParams.min_yield) || 15;

  const supabase = getSupabase("aa_tools");

  const [{ data: stacksRaw, error }, { data: sessionRow }] = await Promise.all([
    supabase
      .from("stack_view")
      .select("*")
      .gte("combined_yield", minYield)
      .order("combined_yield", { ascending: false })
      .limit(50),
    supabase
      .from("session_state")
      .select("last_success_at")
      .eq("source", "simplymiles")
      .limit(1),
  ]);
  const stacks = (stacksRaw ?? []) as Stack[];
  const smLastSuccess = sessionRow?.[0]?.last_success_at as string | undefined;

  return (
    <main className="max-w-7xl mx-auto px-4 py-6">
      <div className="mb-6">
        <div className="flex items-baseline justify-between">
          <h1 className="text-2xl font-bold tracking-tight">AA Stacks</h1>
          {smLastSuccess && (
            <span className="text-xs text-gray-400">
              SimplyMiles: {formatRelative(smLastSuccess)}
            </span>
          )}
        </div>
        <p className="text-sm text-gray-500">
          Portal × SimplyMiles combos. Use AA Mastercard at checkout to add +1 mi/$ on top.
        </p>
      </div>

      <form className="flex flex-wrap items-end gap-3 mb-6 bg-white rounded-lg shadow-sm border p-4">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Min Yield</label>
          <select name="min_yield" defaultValue={String(minYield)} className="border rounded-md px-3 py-2 text-sm bg-white">
            <option value="10">10x+</option>
            <option value="15">15x+</option>
            <option value="20">20x+</option>
            <option value="30">30x+</option>
          </select>
        </div>
        <button type="submit" className="bg-blue-600 text-white rounded-md px-5 py-2 text-sm font-medium hover:bg-blue-700 transition-colors">
          Filter
        </button>
      </form>

      {error && (
        <div className="bg-red-50 text-red-700 rounded-lg p-4 mb-6 text-sm">
          {error.message?.toLowerCase().includes("schema") || error.message?.toLowerCase().includes("relation") ? (
            <>
              <p className="font-medium">Database schema needs re-registration</p>
              <p className="mt-1 text-red-600">
                The aa_tools schema fell out of the PostgREST exposed list.
                Run:{" "}
                <code className="bg-red-100 px-1.5 py-0.5 rounded text-xs font-mono">
                  SELECT public.register_exposed_schema(&apos;aa_tools&apos;)
                </code>
                {" "}then add{" "}
                <code className="bg-red-100 px-1.5 py-0.5 rounded text-xs font-mono">aa_tools</code>
                {" "}in Dashboard &gt; API &gt; Exposed Schemas.
              </p>
            </>
          ) : (
            <>Failed to load stacks: {error.message}</>
          )}
        </div>
      )}

      <div className="bg-white rounded-lg shadow-sm border overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-gray-50 text-left">
              <th className="px-4 py-3 font-medium text-gray-600">Merchant</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-right">Portal</th>
              <th className="px-4 py-3 font-medium text-gray-600">SimplyMiles</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-right">Combined</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-right">Expires</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-right">Updated</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {stacks.length > 0 ? (
              stacks.map((s) => (
                <tr key={s.merchant_name_normalized} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    {s.portal_click_url ? (
                      <a href={s.portal_click_url} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-600 hover:underline">
                        {s.merchant_name}
                      </a>
                    ) : (
                      <span className="font-medium text-gray-900">{s.merchant_name}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className="font-medium text-gray-700">{Number(s.portal_rate).toFixed(0)}x</span>
                    {s.portal_is_elevated && <span className="ml-1 text-amber-500" title="Elevated rate">✨</span>}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{formatSmOffer(s)}</td>
                  <td className="px-4 py-3 text-right">
                    <span className={`font-bold ${Number(s.combined_yield) >= 40 ? "text-emerald-600" : Number(s.combined_yield) >= 25 ? "text-green-600" : "text-lime-600"}`}>
                      {Number(s.combined_yield).toFixed(1)}x
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-gray-500 whitespace-nowrap">
                    {formatExpiry(s.sm_expires_at)}
                  </td>
                  <td className="px-4 py-3 text-right text-xs text-gray-400 whitespace-nowrap">
                    {formatRelative(s.last_scraped_at)}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-gray-400">
                  No stacks at {minYield}x+. Portal and SimplyMiles may not have overlap yet — check back after next scrape cycle (portal every 6h, SM every 4h).
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 text-xs text-gray-400 text-center">
        {stacks.length} stacks · showing ≥{minYield}x combined yield
      </div>
    </main>
  );
}
