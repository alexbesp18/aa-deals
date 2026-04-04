import { getSupabase } from "@/lib/supabase";
import { markAsBooked } from "./actions";

const BRANDS: Record<string, string> = {
  hilton: "Hilton Family",
  marriott: "Marriott Family",
  ihg: "IHG Family",
  hyatt: "Hyatt Family",
  all: "All Brands",
};

const STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DC","DE","FL","GA","HI","ID","IL","IN",
  "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH",
  "NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT",
  "VT","VA","WA","WV","WI","WY",
];

function starsDisplay(n: number) {
  return n > 0 ? "\u2605".repeat(n) + "\u2606".repeat(5 - n) : "\u2014";
}

function bookingUrl(agodaHotelId: string | null, checkIn: string, checkOut: string) {
  if (!agodaHotelId) return null;
  const fmtDate = (d: string) => {
    const [y, m, day] = d.split("-");
    return `${m}/${day}/${y}`;
  };
  return `https://www.aadvantagehotels.com/hotel/${agodaHotelId}?checkIn=${fmtDate(checkIn)}&checkOut=${fmtDate(checkOut)}&rooms=1&adults=2&mode=earn`;
}

export const dynamic = "force-dynamic";

export default async function Page(props: {
  searchParams: Promise<{ brand?: string; state?: string }>;
}) {
  const searchParams = await props.searchParams;
  const brand = searchParams.brand || "hilton";
  const stateFilter = searchParams.state || "all";

  const supabase = getSupabase();

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  let query = supabase
    .from("deals")
    .select("*")
    .eq("is_booked", false)
    .gte("yield_ratio", 30)
    .gte("check_in", todayStr)
    .order("yield_ratio", { ascending: false })
    .limit(200);

  if (brand !== "all") {
    query = query.eq("brand", brand);
  }
  if (stateFilter !== "all") {
    query = query.eq("state", stateFilter);
  }

  const { data: deals, error } = await query;
  const dealCount = deals?.length ?? 0;

  return (
    <main className="max-w-7xl mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">AA Hotel Deals</h1>
        <p className="text-sm text-gray-500">
          30x+ miles per dollar redemptions via aadvantagehotels.com
        </p>
      </div>

      <form className="flex flex-wrap items-end gap-3 mb-6 bg-white rounded-lg shadow-sm border p-4">
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
              <th className="px-4 py-3 font-medium text-gray-600 text-center">Stars</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-right">Yield</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-right">Cost</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-right">Miles</th>
              <th className="px-4 py-3 font-medium text-gray-600">Dates</th>
              <th className="px-4 py-3 font-medium text-gray-600 text-center">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {deals && deals.length > 0 ? (
              deals.map((deal) => {
                const url = deal.url || bookingUrl(deal.agoda_hotel_id, deal.check_in, deal.check_out);
                return (
                  <tr key={deal.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-900 max-w-[220px] truncate">
                        {url ? (
                          <a href={url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                            {deal.hotel_name}
                          </a>
                        ) : (
                          deal.hotel_name
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                      {deal.city_name}, {deal.state}
                    </td>
                    <td className="px-4 py-3 text-center text-amber-500 text-xs tracking-tight">
                      {starsDisplay(deal.stars)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className={`font-bold ${deal.yield_ratio >= 50 ? "text-emerald-600" : deal.yield_ratio >= 40 ? "text-green-600" : "text-lime-600"}`}>
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
                      {deal.check_in}
                      <span className="text-gray-400 text-xs ml-1">({deal.nights}n)</span>
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
                <td colSpan={8} className="px-4 py-12 text-center text-gray-400">
                  {error ? "Error loading deals" : "No 30x+ deals found. Run the scraper to populate data."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 text-xs text-gray-400 text-center">
        {dealCount} deals shown
      </div>
    </main>
  );
}
