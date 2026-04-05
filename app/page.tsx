import { getSupabase } from "@/lib/supabase";
import { markAsBooked } from "./actions";

const BRANDS: Record<string, string> = {
  all: "All Brands",
  hilton: "Hilton Family",
  marriott: "Marriott Family",
  ihg: "IHG Family",
  hyatt: "Hyatt Family",
  wyndham: "Wyndham Family",
  bestwestern: "Best Western",
  choice: "Choice Hotels",
};

const STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DC","DE","FL","GA","HI","ID","IL","IN",
  "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH",
  "NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT",
  "VT","VA","WA","WV","WI","WY",
];

function formatDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y!, m! - 1, d!);
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function dealUrl(deal: { url: string | null; city_name: string; check_in: string; check_out: string }) {
  // New URLs use /search?... which works. Old URLs use /hotel/{id} which 404s.
  if (deal.url && deal.url.includes("/search?")) return deal.url;
  // Fallback: construct search URL from city + dates
  const fmtD = (iso: string) => { const [y, m, d] = iso.split("-"); return `${m}/${d}/${y}`; };
  return `https://www.aadvantagehotels.com/search?adults=2&checkIn=${encodeURIComponent(fmtD(deal.check_in))}&checkOut=${encodeURIComponent(fmtD(deal.check_out))}&currency=USD&language=en&mode=earn&program=aadvantage&query=${encodeURIComponent(deal.city_name)}&rooms=1&source=AGODA`;
}

export const dynamic = "force-dynamic";

export default async function Page(props: {
  searchParams: Promise<{ brand?: string; state?: string; min_yield?: string }>;
}) {
  const searchParams = await props.searchParams;
  const brand = searchParams.brand || "hilton";
  const stateFilter = searchParams.state || "all";
  const minYield = Number(searchParams.min_yield) || 30;

  const supabase = getSupabase();

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  let query = supabase
    .from("deals")
    .select("id, hotel_name, city_name, state, yield_ratio, total_cost, total_miles, check_in, check_out, url")
    .eq("is_booked", false)
    .gte("yield_ratio", minYield)
    .gte("check_in", todayStr)
    .order("yield_ratio", { ascending: false })
    .limit(200);

  if (brand !== "all") {
    query = query.eq("brand", brand);
  }
  if (stateFilter !== "all") {
    query = query.eq("state", stateFilter);
  }

  // Parallel queries — no waterfall
  const [{ data: deals, error }, { data: lastScrape }] = await Promise.all([
    query,
    supabase.from("scrape_progress").select("completed_at").order("completed_at", { ascending: false }).limit(1),
  ]);
  const dealCount = deals?.length ?? 0;
  const lastScraped = lastScrape?.[0]?.completed_at;

  return (
    <main className="max-w-7xl mx-auto px-4 py-6">
      <div className="mb-6">
        <div className="flex items-baseline justify-between">
          <h1 className="text-2xl font-bold tracking-tight">AA Hotel Deals</h1>
          {lastScraped && (
            <span className="text-xs text-gray-400">
              Last scraped: {new Date(lastScraped).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
            </span>
          )}
        </div>
        <p className="text-sm text-gray-500">
          Cherry-picked miles/dollar redemptions via aadvantagehotels.com
        </p>
      </div>

      <form className="flex flex-wrap items-end gap-3 mb-6 bg-white rounded-lg shadow-sm border p-4">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Min Yield</label>
          <select name="min_yield" defaultValue={String(minYield)} className="border rounded-md px-3 py-2 text-sm bg-white">
            <option value="15">15x+</option>
            <option value="20">20x+</option>
            <option value="25">25x+</option>
            <option value="30">30x+</option>
            <option value="40">40x+</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Brand</label>
          <select name="brand" defaultValue={brand} className="border rounded-md px-3 py-2 text-sm bg-white">
            {Object.entries(BRANDS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">State</label>
          <select name="state" defaultValue={stateFilter} className="border rounded-md px-3 py-2 text-sm bg-white">
            <option value="all">All States</option>
            {STATES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <button type="submit" className="bg-blue-600 text-white rounded-md px-5 py-2 text-sm font-medium hover:bg-blue-700 transition-colors">
          Filter
        </button>
      </form>

      {error && (
        <div className="bg-red-50 text-red-700 rounded-lg p-4 mb-6 text-sm">
          Failed to load deals: {error.message}
        </div>
      )}

      <div className="bg-white rounded-lg shadow-sm border overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-gray-50 text-left">
              <th className="px-4 py-3 font-medium text-gray-600">Hotel</th>
              <th className="px-4 py-3 font-medium text-gray-600">Location</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-right">Yield</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-right">Cost</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-right">Miles</th>
              <th className="px-4 py-3 font-medium text-gray-600">Date</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-center w-32">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {deals && deals.length > 0 ? (
              deals.map((deal) => {
                const url = dealUrl(deal);
                return (
                  <tr key={deal.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      {url ? (
                        <a href={url} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-600 hover:underline">
                          {deal.hotel_name}
                        </a>
                      ) : (
                        <span className="font-medium text-gray-900">{deal.hotel_name}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                      {deal.city_name}, {deal.state}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className={`font-bold ${deal.yield_ratio >= 40 ? "text-emerald-600" : deal.yield_ratio >= 30 ? "text-green-600" : "text-lime-600"}`}>
                        {Number(deal.yield_ratio).toFixed(1)}x
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      ${Number(deal.total_cost).toFixed(0)}
                    </td>
                    <td className="px-4 py-3 text-right font-medium text-purple-600">
                      {Number(deal.total_miles).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                      {formatDate(deal.check_in)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <div className="flex items-center justify-center gap-2">
                        {url && (
                          <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center bg-blue-600 text-white text-xs font-medium rounded px-2.5 py-1 hover:bg-blue-700 transition-colors">
                            Book
                          </a>
                        )}
                        <form action={markAsBooked}>
                          <input type="hidden" name="id" value={deal.id} />
                          <button type="submit" className="inline-flex items-center bg-gray-100 text-gray-600 text-xs font-medium rounded px-2.5 py-1 hover:bg-green-100 hover:text-green-700 transition-colors" title="Mark as booked">
                            Booked
                          </button>
                        </form>
                      </div>
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                  No deals found at {minYield}x+{brand !== "all" ? ` for ${BRANDS[brand]}` : ""}. Try lowering the yield filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 text-xs text-gray-400 text-center">
        {dealCount} deals
      </div>
    </main>
  );
}
