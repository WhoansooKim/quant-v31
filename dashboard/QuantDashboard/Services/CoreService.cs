using System.Text.Json;
using Npgsql;

namespace QuantDashboard.Services;

/// <summary>
/// §22.AO-71 코어 운용 화면 — 실계좌(코어 70 + J 30) vs 섀도(core_only · b_offJ), 추세 상태, J 슬리브.
/// 엔진 swing_pipeline_log(core_allocate) · core_shadow · swing_snapshots · swing_positions(side=CORE) 를 읽기만 한다.
/// </summary>
public class CoreService
{
    private readonly string _connStr;
    private readonly ILogger<CoreService> _logger;
    private static readonly HashSet<string> CoreSleeveSyms = new() { "UPRO", "BIL" };

    public CoreService(string connStr, ILogger<CoreService> logger)
    {
        _connStr = connStr;
        _logger = logger;
    }

    public record CoreLot(string Symbol, decimal Qty, decimal EntryPrice, decimal? CurrentPrice, DateTime EntryTime, bool IsJ);
    public record EquityPoint(DateTime Day, decimal Live, decimal? CoreOnly, decimal? OffJ);
    public record RankRow(int Rank, string Symbol, double Score, bool Held);
    public record CoreView(
        DateTime? LastRun, string? Status, string? Error,
        string? TrendAsOf, double? SpyClose, double? Sma, string? Label, double? Frac,
        double JWeight, string? JLastRebal, string? JAsOf,
        List<CoreLot> Lots, List<EquityPoint> Curve, List<RankRow> Ranking,
        decimal? LatestTotal, decimal Invested);

    public async Task<CoreView> GetAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        // 1) 마지막 core_allocate (상태·오류)
        DateTime? lastRun = null; string? status = null, err = null;
        string? asof = null, label = null; double? close = null, sma = null, frac = null;
        await using (var cmd = new NpgsqlCommand(@"
            SELECT created_at, status, error_msg FROM swing_pipeline_log
            WHERE step_name='core_allocate' ORDER BY created_at DESC LIMIT 1", conn))
        await using (var r = await cmd.ExecuteReaderAsync())
        {
            if (await r.ReadAsync())
            {
                lastRun = r.GetDateTime(0); status = r.GetString(1);
                err = r.IsDBNull(2) ? null : r.GetString(2);
            }
        }
        // 1b) 추세는 trend 세부가 남은 가장 최근 실행에서 — 실패 행은 details 가 비어 있다(2026-11-19 00:30)
        await using (var cmd = new NpgsqlCommand(@"
            SELECT details::text FROM swing_pipeline_log
            WHERE step_name='core_allocate' AND details->'trend' IS NOT NULL
            ORDER BY created_at DESC LIMIT 1", conn))
        await using (var r = await cmd.ExecuteReaderAsync())
        {
            if (await r.ReadAsync())
            {
                if (!r.IsDBNull(0))
                {
                    try
                    {
                        using var d = JsonDocument.Parse(r.GetString(0));
                        if (d.RootElement.TryGetProperty("trend", out var t) && t.ValueKind == JsonValueKind.Object)
                        {
                            asof = t.TryGetProperty("asof", out var a) ? a.GetString() : null;
                            close = t.TryGetProperty("close", out var c) ? c.GetDouble() : null;
                            sma = t.TryGetProperty("sma", out var s) ? s.GetDouble() : null;
                            label = t.TryGetProperty("label", out var l) ? l.GetString() : null;
                            frac = t.TryGetProperty("frac", out var f) ? f.GetDouble() : null;
                        }
                    }
                    catch (JsonException e) { _logger.LogWarning(e, "core_allocate details parse"); }
                }
            }
        }

        // 2) config
        var cfg = new Dictionary<string, string>();
        await using (var cmd = new NpgsqlCommand(@"
            SELECT key, value FROM swing_config
            WHERE key IN ('core_j_weight','core_j_last_rebal','core_j_ranking','initial_capital')", conn))
        await using (var r = await cmd.ExecuteReaderAsync())
            while (await r.ReadAsync()) cfg[r.GetString(0)] = r.IsDBNull(1) ? "" : r.GetString(1);

        // 3) CORE 로트
        var lots = new List<CoreLot>();
        await using (var cmd = new NpgsqlCommand(@"
            SELECT symbol, qty, entry_price, current_price, entry_time FROM swing_positions
            WHERE status='open' AND side='CORE' ORDER BY symbol, entry_time", conn))
        await using (var r = await cmd.ExecuteReaderAsync())
            while (await r.ReadAsync())
            {
                var sym = r.GetString(0);
                lots.Add(new CoreLot(sym, r.GetDecimal(1), r.GetDecimal(2),
                    r.IsDBNull(3) ? null : r.GetDecimal(3), r.GetDateTime(4), !CoreSleeveSyms.Contains(sym)));
            }

        // 4) J 순위
        var held = lots.Where(l => l.IsJ).Select(l => l.Symbol).ToHashSet();
        var ranking = new List<RankRow>();
        string? jAsOf = null;
        if (cfg.TryGetValue("core_j_ranking", out var rk) && rk.StartsWith("{"))
        {
            try
            {
                using var d = JsonDocument.Parse(rk);
                jAsOf = d.RootElement.TryGetProperty("asof", out var a) ? a.GetString() : null;
                var scores = d.RootElement.TryGetProperty("scores", out var sc) ? sc : default;
                int i = 0;
                foreach (var s in d.RootElement.GetProperty("top").EnumerateArray())
                {
                    var sym = s.GetString() ?? "";
                    double v = scores.ValueKind == JsonValueKind.Object && scores.TryGetProperty(sym, out var x) ? x.GetDouble() : double.NaN;
                    ranking.Add(new RankRow(++i, sym, v, held.Contains(sym)));
                }
            }
            catch (JsonException e) { _logger.LogWarning(e, "core_j_ranking parse"); }
        }

        // 5) 곡선: 섀도 시작일부터 일별 마지막 값
        var curve = new List<EquityPoint>();
        var shadow = new Dictionary<(DateTime, string), decimal>();
        DateTime? start = null;
        await using (var cmd = new NpgsqlCommand(@"
            SELECT DISTINCT ON (variant, (time AT TIME ZONE 'Asia/Seoul')::date)
                   (time AT TIME ZONE 'Asia/Seoul')::date d, variant, equity
            FROM core_shadow ORDER BY variant, (time AT TIME ZONE 'Asia/Seoul')::date, time DESC", conn))
        await using (var r = await cmd.ExecuteReaderAsync())
            while (await r.ReadAsync())
            {
                var d = r.GetDateTime(0);
                shadow[(d, r.GetString(1))] = r.GetDecimal(2);
                if (start == null || d < start) start = d;
            }
        decimal? latestTotal = null;
        await using (var cmd = new NpgsqlCommand(@"
            SELECT DISTINCT ON ((time AT TIME ZONE 'Asia/Seoul')::date)
                   (time AT TIME ZONE 'Asia/Seoul')::date d, total_value_usd
            FROM swing_snapshots WHERE time >= @s
            ORDER BY (time AT TIME ZONE 'Asia/Seoul')::date, time DESC", conn))
        {
            cmd.Parameters.AddWithValue("s", (start ?? DateTime.Today).AddDays(-1));
            await using var r = await cmd.ExecuteReaderAsync();
            while (await r.ReadAsync())
            {
                var d = r.GetDateTime(0);
                var live = r.GetDecimal(1);
                latestTotal = live;
                if (start != null && d >= start)
                    curve.Add(new EquityPoint(d, live,
                        shadow.TryGetValue((d, "core_only"), out var a) ? a : null,
                        shadow.TryGetValue((d, "b_offJ"), out var b) ? b : null));
            }
        }

        decimal invested = 0;
        await using (var cmd = new NpgsqlCommand(@"SELECT COALESCE(SUM(CASE WHEN event_type='deposit' THEN amount
                     WHEN event_type='withdraw' THEN -amount ELSE 0 END),0) FROM swing_capital_events", conn))
        {
            try { invested = Convert.ToDecimal(await cmd.ExecuteScalarAsync()); }
            catch (PostgresException) { invested = 0; }
        }
        invested += decimal.TryParse(cfg.GetValueOrDefault("initial_capital", "0"), out var ic) ? ic : 0;

        return new CoreView(lastRun, status, err, asof, close, sma, label, frac,
            double.TryParse(cfg.GetValueOrDefault("core_j_weight", "0"), out var jw) ? jw : 0,
            cfg.GetValueOrDefault("core_j_last_rebal"), jAsOf, lots, curve, ranking, latestTotal, invested);
    }
}
