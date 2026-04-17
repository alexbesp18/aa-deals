import { getSupabase } from "@/lib/supabase";
import { markAsBooked } from "./actions";

const US_STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DC","DE","FL","GA","HI","ID","IL","IN",
  "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH",
  "NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT",
  "VT","VA","WA","WV","WI","WY","PR",
];

const BRAND_MODES: Record<string, string> = {
  all: "All Brands",
  hilton: "Hilton Family",
  sub_brand: "Hilton Sub-Brands Only",
};

const REGIONS: Record<string, string> = {
  us: "United States only",
  intl: "International only",
  all: "US + International",
};

const SUB_BRANDS_HONORS_BONUS = new Set(["Hampton", "HiltonGardenInn", "Tru"]);
const HONORS_BONUS_START = "2026-04-07";
const HONORS_BONUS_END = "2026-12-31";

function formatDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y!, m! - 1, d!);
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatSubBrand(s: string | null): string {
  if (!s) return "";
  if (s === "HiltonGardenInn") return "HGI";
  if (s === "DoubleTree") return "DT";
  return s;
}

function qualifiesForHonorsBonus(d: Deal): boolean {
  return (
    !!d.sub_brand &&
    SUB_BRANDS_HONORS_BONUS.has(d.sub_brand) &&
    US_STATES.includes(d.state) &&
    d.check_in >= HONORS_BONUS_START &&
    d.check_in <= HONORS_BONUS_END
  );
}

function dealUrl(deal: { url: string | null; city_name: string; check_in: string; check_out: string }) {
  if (deal.url && deal.url.includes("/search?")) return deal.url;
  const fmtD = (iso: string) => { const [y, m, d] = iso.split("-"); return `${m}/${d}/${y}`; };
  return `https://www.aadvantagehotels.com/search?adults=2&checkIn=${encodeURIComponent(fmtD(deal.check_in))}&checkOut=${encodeURIComponent(fmtD(deal.check_out))}&currency=USD&language=en&mode=earn&program=aadvantage&query=${encodeURIComponent(deal.city_name)}&rooms=1&source=AGODA`;
}

type Deal = {
  id: number;
  hotel_name: string;
  brand: string | null;
  sub_brand: string | null;
  city_name: string;
  state: string;
  yield_ratio: number;
  total_cost: number;
  total_miles: number;
  check_in: string;
  check_out: string;
  url: string | null;
};

export const dynamic = "force-dynamic";

export default async function Page(props: {
  searchParams: Promise<{ brand_mode?: string; state?: string; min_yield?: string; region?: string }>;
}) {
  const searchParams = await props.searchParams;
  const brandMode = ["all","hilton","sub_brand"].includes(searchParams.brand_mode || "")
    ? (searchParams.brand_mode as string)
    : "all";
  const region = ["us","intl","all"].includes(searchParams.region || "")
    ? (searchParams.region as string)
    : "us";
  const stateFilter = searchParams.state || "all";
  const minYield = Number(searchParams.min_yield) || 30;

  const supabase = getSupabase();
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  // deals_best view = 1 row per (hotel_name, state) with best yield
  let query = supabase
    .from("deals_best")
    .select("id, hotel_name, brand, sub_brand, city_name, state, yield_ratio, total_cost, total_miles, check_in, check_out, url")
    .gte("yield_ratio", minYield)
    .gte("check_in", todayStr)
    .order("yield_ratio", { ascending: false })
    .order("total_cost", { ascending: true })
    .limit(300);

  if (brandMode === "hilton") query = query.eq("brand", "hilton");
  if (brandMode === "sub_brand") query = query.not("sub_brand", "is", null);
  if (region === "us") query = query.in("state", US_STATES);
  if (region === "intl") query = query.not("state", "in", `(${US_STATES.map(s => `"${s}"`).join(",")})`);
  if (stateFilter !== "all") query = query.eq("state", stateFilter);

  // Gems: top 1 per sub-brand at 30x+, US only
  const gemsQuery = supabase
    .from("deals_best")
    .select("id, hotel_name, brand, sub_brand, city_name, state, yield_ratio, total_cost, total_miles, check_in, check_out, url")
    .gte("yield_ratio", 30)
    .not("sub_brand", "is", null)
    .gte("check_in", todayStr)
    .in("state", US_STATES)
    .order("yield_ratio", { ascending: false })
    .order("total_cost", { ascending: true })
    .limit(20);

  const [{ data: deals, error }, { data: scrapeProgress }, { data: gemsRaw }] = await Promise.all([
    query,
    supabase.from("scrape_progress").select("completed_at").order("completed_at", { ascending: false }).limit(1),
    gemsQuery,
  ]);

  const lastScraped = scrapeProgress?.[0]?.completed_at;
  const dealCount = deals?.length ?? 0;

  // Top 1 per sub-brand — since view already gives 1 per property, just take first of each sub_brand
  const gemsBySubBrand = new Map<string, Deal[]>();
  for (const d of (gemsRaw ?? []) as Deal[]) {
    if (!d.sub_brand) continue;
    const list = gemsBySubBrand.get(d.sub_brand) ?? [];
    if (list.length < 2) {
      list.push(d);
      gemsBySubBrand.set(d.sub_brand, list);
    }
  }
  const gemIds = new Set<number>();
  for (const list of gemsBySubBrand.values()) for (const g of list) gemIds.add(g.id);
  const showGems = (brandMode === "all" || brandMode === "sub_brand") && gemsBySubBrand.size > 0;

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
          Cap-hit hotels at 30x+ miles/$ on aadvantagehotels.com. One row per property · cheapest date at peak yield.
        </p>
      </div>

      <form className="flex flex-wrap items-end gap-3 mb-6 bg-white rounded-lg shadow-sm border p-4">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Min Yield</label>
          <select name="min_yield" defaultValue={String(minYield)} className="border rounded-md px-3 py-2 text-sm bg-white">
            <option value="25">25x+ (backup)</option>
            <option value="30">30x+ (target)</option>
            <option value="35">35x+ (premium)</option>
            <option value="40">40x+ (exceptional)</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Region</label>
          <select name="region" defaultValue={region} className="border rounded-md px-3 py-2 text-sm bg-white">
            {Object.entries(REGIONS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Brand Mode</label>
          <select name="brand_mode" defaultValue={brandMode} className="border rounded-md px-3 py-2 text-sm bg-white">
            {Object.entries(BRAND_MODES).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">State</label>
          <select name="state" defaultValue={stateFilter} className="border rounded-md px-3 py-2 text-sm bg-white">
            <option value="all">All States</option>
            {US_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
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
                Next scraper run will auto-fix. If persistent, run:{" "}
                <code className="bg-red-100 px-1.5 py-0.5 rounded text-xs font-mono">SELECT public.register_exposed_schema(&apos;aa_hotels&apos;)</code>
              </p>
            </>
          ) : (
            <>Failed to load deals: {error.message}</>
          )}
        </div>
      )}

      {showGems && (
        <div className="mb-6 bg-amber-50 border border-amber-200 rounded-lg p-4">
          <h2 className="text-sm font-bold text-amber-800 mb-3">
            ⭐ US sub-brand gems (30x+, walk-in-friendly)
          </h2>
          <div className="space-y-1 text-sm">
            {Array.from(gemsBySubBrand.entries()).map(([subBrand, list]) => (
              <div key={subBrand} className="flex flex-wrap gap-x-3 items-baseline">
                <span className="font-semibold text-amber-700 min-w-[90px]">{formatSubBrand(subBrand)}:</span>
                {list.map((g) => (
                  <a
                    key={g.id}
                    href={dealUrl(g)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline text-xs"
                    title={g.hotel_name}
                  >
                    {g.city_name}, {g.state} · {Number(g.yield_ratio).toFixed(1)}x · ${Number(g.total_cost).toFixed(0)}
                  </a>
                ))}
              </div>
            ))}
          </div>
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
              <th className="px-4 py-3 font-medium text-gray-600">Best Date</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-center w-32">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {deals && deals.length > 0 ? (
              (deals as Deal[]).map((deal) => {
                const url = dealUrl(deal);
                const isGem = gemIds.has(deal.id);
                const hasHonorsBonus = qualifiesForHonorsBonus(deal);
                return (
                  <tr key={deal.id} className={`hover:bg-gray-50 ${isGem ? "bg-amber-50/40" : ""}`}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {isGem && <span title="US sub-brand gem">⭐</span>}
                        {url ? (
                          <a href={url} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-600 hover:underline">
                            {deal.hotel_name}
                          </a>
                        ) : (
                          <span className="font-medium text-gray-900">{deal.hotel_name}</span>
                        )}
                        {deal.sub_brand && (
                          <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                            {formatSubBrand(deal.sub_brand)}
                          </span>
                        )}
                        {hasHonorsBonus && (
                          <span
                            className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded"
                            title="Hilton Honors bonus: +2,500 Honors on top of AA LP (Apr 7 – Dec 31, 2026, book by July 1)"
                          >
                            +2.5k HH
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                      {deal.city_name}, {deal.state}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className={`font-bold ${deal.yield_ratio >= 35 ? "text-emerald-600" : deal.yield_ratio >= 30 ? "text-green-600" : "text-lime-600"}`}>
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
                  No deals at {minYield}x+ {brandMode !== "all" ? `for ${BRAND_MODES[brandMode]}` : ""}
                  {region !== "all" ? ` in ${REGIONS[region]}` : ""}
                  {stateFilter !== "all" ? ` (state: ${stateFilter})` : ""}.
                  {" "}Try dropping yield to 25x+ or switching region.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 text-xs text-gray-400 text-center">
        {dealCount} unique properties · 1 row per hotel at best date · {REGIONS[region]}
      </div>
    </main>
  );
}
