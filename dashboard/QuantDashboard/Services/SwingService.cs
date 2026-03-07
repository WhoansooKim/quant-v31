using Npgsql;
using QuantDashboard.Models;

namespace QuantDashboard.Services;

/// <summary>
/// Swing Trading 전용 PostgreSQL 서비스 (Npgsql Raw SQL)
/// swing_ 테이블 + daily_prices 조회
/// </summary>
public class SwingService
{
    private readonly string _connStr;
    private readonly ILogger<SwingService> _logger;

    public SwingService(string connectionString, ILogger<SwingService> logger)
    {
        _connStr = connectionString;
        _logger = logger;
    }

    // ═══════════════════════════════════════
    // Signals
    // ═══════════════════════════════════════

    public async Task<List<SwingSignal>> GetSignalsAsync(string? status = null, int limit = 50)
    {
        var signals = new List<SwingSignal>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        var sql = status != null
            ? @"SELECT signal_id, time, symbol, signal_type, entry_price,
                       stop_loss, take_profit, return_20d_rank, trend_aligned,
                       breakout_5d, volume_surge, exit_reason, position_id,
                       status, approved_at, executed_at,
                       llm_score, llm_analysis, llm_analyzed_at,
                       technical_score, sentiment_score, flow_score,
                       composite_score, factor_detail, factor_scored_at
                FROM swing_signals WHERE status = @status
                ORDER BY time DESC LIMIT @limit"
            : @"SELECT signal_id, time, symbol, signal_type, entry_price,
                       stop_loss, take_profit, return_20d_rank, trend_aligned,
                       breakout_5d, volume_surge, exit_reason, position_id,
                       status, approved_at, executed_at,
                       llm_score, llm_analysis, llm_analyzed_at,
                       technical_score, sentiment_score, flow_score,
                       composite_score, factor_detail, factor_scored_at
                FROM swing_signals ORDER BY time DESC LIMIT @limit";

        await using var cmd = new NpgsqlCommand(sql, conn);
        if (status != null) cmd.Parameters.AddWithValue("@status", status);
        cmd.Parameters.AddWithValue("@limit", limit);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            signals.Add(new SwingSignal(
                SignalId: r.GetInt64(0),
                Time: r.GetDateTime(1),
                Symbol: r.GetString(2),
                SignalType: r.GetString(3),
                EntryPrice: r.IsDBNull(4) ? null : r.GetDecimal(4),
                StopLoss: r.IsDBNull(5) ? null : r.GetDecimal(5),
                TakeProfit: r.IsDBNull(6) ? null : r.GetDecimal(6),
                Return20dRank: r.IsDBNull(7) ? null : r.GetDouble(7),
                TrendAligned: !r.IsDBNull(8) && r.GetBoolean(8),
                Breakout5d: !r.IsDBNull(9) && r.GetBoolean(9),
                VolumeSurge: !r.IsDBNull(10) && r.GetBoolean(10),
                ExitReason: r.IsDBNull(11) ? null : r.GetString(11),
                PositionId: r.IsDBNull(12) ? null : r.GetInt64(12),
                Status: r.GetString(13),
                ApprovedAt: r.IsDBNull(14) ? null : r.GetDateTime(14),
                ExecutedAt: r.IsDBNull(15) ? null : r.GetDateTime(15),
                LlmScore: r.IsDBNull(16) ? null : r.GetInt32(16),
                LlmAnalysis: r.IsDBNull(17) ? null : r.GetString(17),
                LlmAnalyzedAt: r.IsDBNull(18) ? null : r.GetDateTime(18),
                TechnicalScore: r.IsDBNull(19) ? null : r.GetDouble(19),
                SentimentScore: r.IsDBNull(20) ? null : r.GetDouble(20),
                FlowScore: r.IsDBNull(21) ? null : r.GetDouble(21),
                CompositeScore: r.IsDBNull(22) ? null : r.GetDouble(22),
                FactorDetail: r.IsDBNull(23) ? null : r.GetString(23),
                FactorScoredAt: r.IsDBNull(24) ? null : r.GetDateTime(24)
            ));
        }
        return signals;
    }

    public async Task<bool> RevertToPendingAsync(long signalId)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            UPDATE swing_signals
            SET status = 'pending', approved_at = NULL, executed_at = NULL
            WHERE signal_id = @id AND status IN ('approved', 'rejected')", conn);
        cmd.Parameters.AddWithValue("@id", signalId);
        return await cmd.ExecuteNonQueryAsync() > 0;
    }

    public async Task<int> GetPendingSignalCountAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT count(*) FROM swing_signals WHERE status = 'pending'", conn);
        var result = await cmd.ExecuteScalarAsync();
        return Convert.ToInt32(result);
    }

    // ═══════════════════════════════════════
    // Positions
    // ═══════════════════════════════════════

    public async Task<List<SwingPosition>> GetOpenPositionsAsync()
    {
        return await GetPositionsAsync("open");
    }

    public async Task<List<SwingPosition>> GetClosedPositionsAsync(int limit = 50)
    {
        return await GetPositionsAsync("closed", limit);
    }

    private async Task<List<SwingPosition>> GetPositionsAsync(string status, int limit = 50)
    {
        var positions = new List<SwingPosition>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        var orderCol = status == "open" ? "entry_time" : "exit_time";
        await using var cmd = new NpgsqlCommand($@"
            SELECT position_id, symbol, side, qty, entry_price, entry_time,
                   stop_loss, take_profit, current_price, unrealized_pnl,
                   unrealized_pct, status, exit_price, exit_time, exit_reason,
                   realized_pnl, realized_pct, hold_days, signal_id, is_paper,
                   partial_exited, trailing_stop_active, high_water_mark
            FROM swing_positions
            WHERE status = @status
            ORDER BY {orderCol} DESC LIMIT @limit", conn);
        cmd.Parameters.AddWithValue("@status", status);
        cmd.Parameters.AddWithValue("@limit", limit);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            positions.Add(new SwingPosition(
                PositionId: r.GetInt64(0),
                Symbol: r.GetString(1),
                Side: r.GetString(2),
                Qty: r.GetDecimal(3),
                EntryPrice: r.GetDecimal(4),
                EntryTime: r.GetDateTime(5),
                StopLoss: r.IsDBNull(6) ? null : r.GetDecimal(6),
                TakeProfit: r.IsDBNull(7) ? null : r.GetDecimal(7),
                CurrentPrice: r.IsDBNull(8) ? null : r.GetDecimal(8),
                UnrealizedPnl: r.IsDBNull(9) ? null : r.GetDecimal(9),
                UnrealizedPct: r.IsDBNull(10) ? null : r.GetDouble(10),
                Status: r.GetString(11),
                ExitPrice: r.IsDBNull(12) ? null : r.GetDecimal(12),
                ExitTime: r.IsDBNull(13) ? null : r.GetDateTime(13),
                ExitReason: r.IsDBNull(14) ? null : r.GetString(14),
                RealizedPnl: r.IsDBNull(15) ? null : r.GetDecimal(15),
                RealizedPct: r.IsDBNull(16) ? null : r.GetDouble(16),
                HoldDays: r.IsDBNull(17) ? null : r.GetInt32(17),
                SignalId: r.IsDBNull(18) ? null : r.GetInt64(18),
                IsPaper: r.GetBoolean(19),
                PartialExited: !r.IsDBNull(20) && r.GetBoolean(20),
                TrailingStopActive: !r.IsDBNull(21) && r.GetBoolean(21),
                HighWaterMark: r.IsDBNull(22) ? null : r.GetDecimal(22)
            ));
        }
        return positions;
    }

    // ═══════════════════════════════════════
    // Trades
    // ═══════════════════════════════════════

    public async Task<List<SwingTrade>> GetRecentTradesAsync(int limit = 50)
    {
        var trades = new List<SwingTrade>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT trade_id, position_id, signal_id, symbol, side, qty,
                   price, total_amount, order_id, commission, is_paper, executed_at
            FROM swing_trades ORDER BY executed_at DESC LIMIT @limit", conn);
        cmd.Parameters.AddWithValue("@limit", limit);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            trades.Add(new SwingTrade(
                TradeId: r.GetInt64(0),
                PositionId: r.IsDBNull(1) ? null : r.GetInt64(1),
                SignalId: r.IsDBNull(2) ? null : r.GetInt64(2),
                Symbol: r.GetString(3),
                Side: r.GetString(4),
                Qty: r.GetDecimal(5),
                Price: r.GetDecimal(6),
                TotalAmount: r.IsDBNull(7) ? null : r.GetDecimal(7),
                OrderId: r.IsDBNull(8) ? null : r.GetString(8),
                Commission: r.IsDBNull(9) ? null : r.GetDecimal(9),
                IsPaper: r.GetBoolean(10),
                ExecutedAt: r.GetDateTime(11)
            ));
        }
        return trades;
    }

    // ═══════════════════════════════════════
    // Snapshots
    // ═══════════════════════════════════════

    public async Task<SwingSnapshot?> GetLatestSnapshotAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT time, total_value_usd, total_value_krw, cash_usd,
                   invested_usd, daily_pnl_usd, daily_return,
                   cumulative_return, max_drawdown, open_positions, exchange_rate
            FROM swing_snapshots ORDER BY time DESC LIMIT 1", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new SwingSnapshot(
            Time: r.GetDateTime(0),
            TotalValueUsd: r.IsDBNull(1) ? null : r.GetDecimal(1),
            TotalValueKrw: r.IsDBNull(2) ? null : r.GetDecimal(2),
            CashUsd: r.IsDBNull(3) ? null : r.GetDecimal(3),
            InvestedUsd: r.IsDBNull(4) ? null : r.GetDecimal(4),
            DailyPnlUsd: r.IsDBNull(5) ? null : r.GetDecimal(5),
            DailyReturn: r.IsDBNull(6) ? null : r.GetDouble(6),
            CumulativeReturn: r.IsDBNull(7) ? null : r.GetDouble(7),
            MaxDrawdown: r.IsDBNull(8) ? null : r.GetDouble(8),
            OpenPositions: r.IsDBNull(9) ? 0 : r.GetInt32(9),
            ExchangeRate: r.IsDBNull(10) ? null : r.GetDouble(10)
        );
    }

    public async Task<List<SwingSnapshot>> GetSnapshotHistoryAsync(int days = 30)
    {
        var snapshots = new List<SwingSnapshot>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT time, total_value_usd, total_value_krw, cash_usd,
                   invested_usd, daily_pnl_usd, daily_return,
                   cumulative_return, max_drawdown, open_positions, exchange_rate
            FROM swing_snapshots
            WHERE time >= now() - @interval::interval
            ORDER BY time", conn);
        cmd.Parameters.AddWithValue("@interval", $"{days} days");

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            snapshots.Add(new SwingSnapshot(
                Time: r.GetDateTime(0),
                TotalValueUsd: r.IsDBNull(1) ? null : r.GetDecimal(1),
                TotalValueKrw: r.IsDBNull(2) ? null : r.GetDecimal(2),
                CashUsd: r.IsDBNull(3) ? null : r.GetDecimal(3),
                InvestedUsd: r.IsDBNull(4) ? null : r.GetDecimal(4),
                DailyPnlUsd: r.IsDBNull(5) ? null : r.GetDecimal(5),
                DailyReturn: r.IsDBNull(6) ? null : r.GetDouble(6),
                CumulativeReturn: r.IsDBNull(7) ? null : r.GetDouble(7),
                MaxDrawdown: r.IsDBNull(8) ? null : r.GetDouble(8),
                OpenPositions: r.IsDBNull(9) ? 0 : r.GetInt32(9),
                ExchangeRate: r.IsDBNull(10) ? null : r.GetDouble(10)
            ));
        }
        return snapshots;
    }

    // ═══════════════════════════════════════
    // Config
    // ═══════════════════════════════════════

    public async Task<List<SwingConfig>> GetAllConfigAsync()
    {
        var configs = new List<SwingConfig>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT key, value, category, description, updated_at
            FROM swing_config ORDER BY category, key", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            configs.Add(new SwingConfig(
                Key: r.GetString(0),
                Value: r.GetString(1),
                Category: r.GetString(2),
                Description: r.IsDBNull(3) ? null : r.GetString(3),
                UpdatedAt: r.GetDateTime(4)
            ));
        }
        return configs;
    }

    public async Task UpdateConfigAsync(string key, string value)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            UPDATE swing_config SET value = @value, updated_at = now()
            WHERE key = @key", conn);
        cmd.Parameters.AddWithValue("@key", key);
        cmd.Parameters.AddWithValue("@value", value);
        await cmd.ExecuteNonQueryAsync();
    }

    // ═══════════════════════════════════════
    // Backtest
    // ═══════════════════════════════════════

    public async Task<List<SwingBacktestRun>> GetBacktestRunsAsync(int limit = 20)
    {
        var runs = new List<SwingBacktestRun>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT run_id, start_date, end_date, initial_capital, final_value,
                   total_return, cagr, max_drawdown, sharpe_ratio, win_rate,
                   total_trades, profit_factor, avg_hold_days, created_at
            FROM swing_backtest_runs ORDER BY created_at DESC LIMIT @limit", conn);
        cmd.Parameters.AddWithValue("@limit", limit);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            runs.Add(new SwingBacktestRun(
                RunId: r.GetInt64(0),
                StartDate: r.GetDateTime(1),
                EndDate: r.GetDateTime(2),
                InitialCapital: r.IsDBNull(3) ? null : r.GetDecimal(3),
                FinalValue: r.IsDBNull(4) ? null : r.GetDecimal(4),
                TotalReturn: r.IsDBNull(5) ? null : r.GetDouble(5),
                Cagr: r.IsDBNull(6) ? null : r.GetDouble(6),
                MaxDrawdown: r.IsDBNull(7) ? null : r.GetDouble(7),
                SharpeRatio: r.IsDBNull(8) ? null : r.GetDouble(8),
                WinRate: r.IsDBNull(9) ? null : r.GetDouble(9),
                TotalTrades: r.IsDBNull(10) ? null : r.GetInt32(10),
                ProfitFactor: r.IsDBNull(11) ? null : r.GetDouble(11),
                AvgHoldDays: r.IsDBNull(12) ? null : r.GetDouble(12),
                CreatedAt: r.GetDateTime(13)
            ));
        }
        return runs;
    }

    public async Task<SwingBacktestRun?> GetLatestBacktestRunAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT run_id, start_date, end_date, initial_capital, final_value,
                   total_return, cagr, max_drawdown, sharpe_ratio, win_rate,
                   total_trades, profit_factor, avg_hold_days, created_at
            FROM swing_backtest_runs ORDER BY created_at DESC LIMIT 1", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new SwingBacktestRun(
            RunId: r.GetInt64(0),
            StartDate: r.GetDateTime(1),
            EndDate: r.GetDateTime(2),
            InitialCapital: r.IsDBNull(3) ? null : r.GetDecimal(3),
            FinalValue: r.IsDBNull(4) ? null : r.GetDecimal(4),
            TotalReturn: r.IsDBNull(5) ? null : r.GetDouble(5),
            Cagr: r.IsDBNull(6) ? null : r.GetDouble(6),
            MaxDrawdown: r.IsDBNull(7) ? null : r.GetDouble(7),
            SharpeRatio: r.IsDBNull(8) ? null : r.GetDouble(8),
            WinRate: r.IsDBNull(9) ? null : r.GetDouble(9),
            TotalTrades: r.IsDBNull(10) ? null : r.GetInt32(10),
            ProfitFactor: r.IsDBNull(11) ? null : r.GetDouble(11),
            AvgHoldDays: r.IsDBNull(12) ? null : r.GetDouble(12),
            CreatedAt: r.GetDateTime(13)
        );
    }

    // ═══════════════════════════════════════
    // Pipeline Log
    // ═══════════════════════════════════════

    public async Task<List<SwingPipelineLog>> GetPipelineLogsAsync(int limit = 20)
    {
        var logs = new List<SwingPipelineLog>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT log_id, step_name, status, elapsed_sec, details::text,
                   error_msg, created_at
            FROM swing_pipeline_log ORDER BY created_at DESC LIMIT @limit", conn);
        cmd.Parameters.AddWithValue("@limit", limit);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            logs.Add(new SwingPipelineLog(
                LogId: r.GetInt64(0),
                StepName: r.GetString(1),
                Status: r.GetString(2),
                ElapsedSec: r.IsDBNull(3) ? null : r.GetDouble(3),
                Details: r.IsDBNull(4) ? null : r.GetString(4),
                ErrorMsg: r.IsDBNull(5) ? null : r.GetString(5),
                CreatedAt: r.GetDateTime(6)
            ));
        }
        return logs;
    }

    // ═══════════════════════════════════════
    // Performance Stats
    // ═══════════════════════════════════════

    public async Task<(int TotalTrades, int WinTrades, decimal TotalPnl, double WinRate)>
        GetPerformanceStatsAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT
                count(*) as total,
                count(*) FILTER (WHERE realized_pnl > 0) as wins,
                coalesce(sum(realized_pnl), 0) as total_pnl
            FROM swing_positions WHERE status = 'closed'", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return (0, 0, 0, 0);

        var total = r.GetInt32(0);
        var wins = r.GetInt32(1);
        var pnl = r.GetDecimal(2);
        var winRate = total > 0 ? (double)wins / total : 0;

        return (total, wins, pnl, winRate);
    }

    // ═══════════════════════════════════════
    // Ticker Bar (기존 유지 — 티커바용 daily_prices)
    // ═══════════════════════════════════════

    public async Task<List<TickerBarItem>> GetTickerBarDataAsync()
    {
        var items = new List<TickerBarItem>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            WITH latest AS (
                SELECT symbol, close,
                       LAG(close) OVER (PARTITION BY symbol ORDER BY time) as prev_close,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY time DESC) as rn
                FROM daily_prices
                WHERE symbol IN ('SPY','QQQ','IWM','VIX','AAPL','MSFT')
                  AND time >= now() - interval '7 days'
            )
            SELECT symbol,
                   close,
                   CASE WHEN prev_close > 0
                        THEN ((close - prev_close) / prev_close * 100)
                        ELSE 0 END as change_pct
            FROM latest WHERE rn = 1
            ORDER BY symbol", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            items.Add(new TickerBarItem(
                Symbol: r.GetString(0),
                Price: r.GetDouble(1),
                ChangePercent: r.IsDBNull(2) ? 0 : r.GetDouble(2)
            ));
        }
        return items;
    }

    // ═══════════════════════════════════════
    // Symbol Detail (팝업)
    // ═══════════════════════════════════════

    public async Task<SwingSymbolDetail?> GetSymbolDetailAsync(string symbol)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        // 1) Universe + Indicators (JOIN)
        await using var cmd1 = new NpgsqlCommand(@"
            SELECT u.symbol, u.company_name, u.sector, u.market_cap, u.index_member,
                   i.close, i.sma_50, i.sma_200, i.return_20d, i.return_20d_rank,
                   i.volume, i.volume_avg_20d, i.volume_ratio,
                   i.trend_aligned, i.breakout_5d, i.volume_surge
            FROM swing_universe u
            LEFT JOIN swing_indicators i ON u.symbol = i.symbol
            WHERE u.symbol = @sym
            LIMIT 1", conn);
        cmd1.Parameters.AddWithValue("@sym", symbol);

        SwingSymbolDetail? detail = null;
        await using (var r = await cmd1.ExecuteReaderAsync())
        {
            if (!await r.ReadAsync()) return null;
            detail = new SwingSymbolDetail
            {
                Symbol = r.GetString(0),
                CompanyName = r.IsDBNull(1) ? null : r.GetString(1),
                Sector = r.IsDBNull(2) ? null : r.GetString(2),
                MarketCap = r.IsDBNull(3) ? null : r.GetDecimal(3),
                IndexMember = r.IsDBNull(4) ? null : r.GetString(4),
                Close = r.IsDBNull(5) ? null : r.GetDecimal(5),
                Sma50 = r.IsDBNull(6) ? null : r.GetDecimal(6),
                Sma200 = r.IsDBNull(7) ? null : r.GetDecimal(7),
                Return20d = r.IsDBNull(8) ? null : r.GetDouble(8),
                Return20dRank = r.IsDBNull(9) ? null : r.GetDouble(9),
                Volume = r.IsDBNull(10) ? null : (long)r.GetDouble(10),
                VolumeAvg20d = r.IsDBNull(11) ? null : (long)r.GetDouble(11),
                VolumeRatio = r.IsDBNull(12) ? null : r.GetDouble(12),
                TrendAligned = !r.IsDBNull(13) && r.GetBoolean(13),
                Breakout5d = !r.IsDBNull(14) && r.GetBoolean(14),
                VolumeSurge = !r.IsDBNull(15) && r.GetBoolean(15),
            };
        }

        // 2) 1M/3M/6M 수익률 (daily_prices)
        await using var cmd2 = new NpgsqlCommand(@"
            WITH latest AS (
                SELECT close FROM daily_prices
                WHERE symbol = @sym ORDER BY time DESC LIMIT 1
            ),
            ago_1m AS (
                SELECT close FROM daily_prices
                WHERE symbol = @sym AND time <= now() - interval '1 month'
                ORDER BY time DESC LIMIT 1
            ),
            ago_3m AS (
                SELECT close FROM daily_prices
                WHERE symbol = @sym AND time <= now() - interval '3 months'
                ORDER BY time DESC LIMIT 1
            ),
            ago_6m AS (
                SELECT close FROM daily_prices
                WHERE symbol = @sym AND time <= now() - interval '6 months'
                ORDER BY time DESC LIMIT 1
            )
            SELECT
                (SELECT close FROM latest) as now_price,
                (SELECT close FROM ago_1m) as p1m,
                (SELECT close FROM ago_3m) as p3m,
                (SELECT close FROM ago_6m) as p6m", conn);
        cmd2.Parameters.AddWithValue("@sym", symbol);

        await using (var r2 = await cmd2.ExecuteReaderAsync())
        {
            if (await r2.ReadAsync())
            {
                var now = r2.IsDBNull(0) ? (double?)null : r2.GetDouble(0);
                var p1m = r2.IsDBNull(1) ? (double?)null : r2.GetDouble(1);
                var p3m = r2.IsDBNull(2) ? (double?)null : r2.GetDouble(2);
                var p6m = r2.IsDBNull(3) ? (double?)null : r2.GetDouble(3);

                if (now.HasValue)
                {
                    detail = detail with
                    {
                        Return1M = p1m.HasValue && p1m > 0 ? (now.Value - p1m.Value) / p1m.Value : null,
                        Return3M = p3m.HasValue && p3m > 0 ? (now.Value - p3m.Value) / p3m.Value : null,
                        Return6M = p6m.HasValue && p6m > 0 ? (now.Value - p6m.Value) / p6m.Value : null,
                    };
                }
            }
        }

        // 3) Latest signal
        await using var cmd3 = new NpgsqlCommand(@"
            SELECT signal_id, time, symbol, signal_type, entry_price,
                   stop_loss, take_profit, return_20d_rank, trend_aligned,
                   breakout_5d, volume_surge, exit_reason, position_id,
                   status, approved_at, executed_at,
                   llm_score, llm_analysis, llm_analyzed_at,
                   technical_score, sentiment_score, flow_score,
                   composite_score, factor_detail, factor_scored_at
            FROM swing_signals WHERE symbol = @sym
            ORDER BY time DESC LIMIT 1", conn);
        cmd3.Parameters.AddWithValue("@sym", symbol);

        await using (var r3 = await cmd3.ExecuteReaderAsync())
        {
            if (await r3.ReadAsync())
            {
                detail = detail with
                {
                    LatestSignal = new SwingSignal(
                        SignalId: r3.GetInt64(0),
                        Time: r3.GetDateTime(1),
                        Symbol: r3.GetString(2),
                        SignalType: r3.GetString(3),
                        EntryPrice: r3.IsDBNull(4) ? null : r3.GetDecimal(4),
                        StopLoss: r3.IsDBNull(5) ? null : r3.GetDecimal(5),
                        TakeProfit: r3.IsDBNull(6) ? null : r3.GetDecimal(6),
                        Return20dRank: r3.IsDBNull(7) ? null : r3.GetDouble(7),
                        TrendAligned: !r3.IsDBNull(8) && r3.GetBoolean(8),
                        Breakout5d: !r3.IsDBNull(9) && r3.GetBoolean(9),
                        VolumeSurge: !r3.IsDBNull(10) && r3.GetBoolean(10),
                        ExitReason: r3.IsDBNull(11) ? null : r3.GetString(11),
                        PositionId: r3.IsDBNull(12) ? null : r3.GetInt64(12),
                        Status: r3.GetString(13),
                        ApprovedAt: r3.IsDBNull(14) ? null : r3.GetDateTime(14),
                        ExecutedAt: r3.IsDBNull(15) ? null : r3.GetDateTime(15),
                        LlmScore: r3.IsDBNull(16) ? null : r3.GetInt32(16),
                        LlmAnalysis: r3.IsDBNull(17) ? null : r3.GetString(17),
                        LlmAnalyzedAt: r3.IsDBNull(18) ? null : r3.GetDateTime(18),
                        TechnicalScore: r3.IsDBNull(19) ? null : r3.GetDouble(19),
                        SentimentScore: r3.IsDBNull(20) ? null : r3.GetDouble(20),
                        FlowScore: r3.IsDBNull(21) ? null : r3.GetDouble(21),
                        CompositeScore: r3.IsDBNull(22) ? null : r3.GetDouble(22),
                        FactorDetail: r3.IsDBNull(23) ? null : r3.GetString(23),
                        FactorScoredAt: r3.IsDBNull(24) ? null : r3.GetDateTime(24)
                    )
                };
            }
        }

        // 4) Open position
        await using var cmd4 = new NpgsqlCommand(@"
            SELECT position_id, symbol, side, qty, entry_price, entry_time,
                   stop_loss, take_profit, current_price, unrealized_pnl,
                   unrealized_pct, status, exit_price, exit_time, exit_reason,
                   realized_pnl, realized_pct, hold_days, signal_id, is_paper,
                   partial_exited, trailing_stop_active, high_water_mark
            FROM swing_positions
            WHERE symbol = @sym AND status = 'open'
            ORDER BY entry_time DESC LIMIT 1", conn);
        cmd4.Parameters.AddWithValue("@sym", symbol);

        await using (var r4 = await cmd4.ExecuteReaderAsync())
        {
            if (await r4.ReadAsync())
            {
                detail = detail with
                {
                    OpenPosition = new SwingPosition(
                        PositionId: r4.GetInt64(0),
                        Symbol: r4.GetString(1),
                        Side: r4.GetString(2),
                        Qty: r4.GetDecimal(3),
                        EntryPrice: r4.GetDecimal(4),
                        EntryTime: r4.GetDateTime(5),
                        StopLoss: r4.IsDBNull(6) ? null : r4.GetDecimal(6),
                        TakeProfit: r4.IsDBNull(7) ? null : r4.GetDecimal(7),
                        CurrentPrice: r4.IsDBNull(8) ? null : r4.GetDecimal(8),
                        UnrealizedPnl: r4.IsDBNull(9) ? null : r4.GetDecimal(9),
                        UnrealizedPct: r4.IsDBNull(10) ? null : r4.GetDouble(10),
                        Status: r4.GetString(11),
                        ExitPrice: r4.IsDBNull(12) ? null : r4.GetDecimal(12),
                        ExitTime: r4.IsDBNull(13) ? null : r4.GetDateTime(13),
                        ExitReason: r4.IsDBNull(14) ? null : r4.GetString(14),
                        RealizedPnl: r4.IsDBNull(15) ? null : r4.GetDecimal(15),
                        RealizedPct: r4.IsDBNull(16) ? null : r4.GetDouble(16),
                        HoldDays: r4.IsDBNull(17) ? null : r4.GetInt32(17),
                        SignalId: r4.IsDBNull(18) ? null : r4.GetInt64(18),
                        IsPaper: r4.GetBoolean(19),
                        PartialExited: !r4.IsDBNull(20) && r4.GetBoolean(20),
                        TrailingStopActive: !r4.IsDBNull(21) && r4.GetBoolean(21),
                        HighWaterMark: r4.IsDBNull(22) ? null : r4.GetDecimal(22)
                    )
                };
            }
        }

        // 5) 진입 스코어 계산 (엔진 로직 미러링)
        var scoreReturn = (detail.Return20dRank ?? 0) >= 0.6 ? 25.0 * ((detail.Return20dRank ?? 0) - 0.6) / 0.4 : 0;
        var scoreTrend = detail.TrendAligned ? 25.0 : 0;
        var scoreBreakout = detail.Breakout5d ? 25.0 : 0;
        var scoreVolume = detail.VolumeSurge ? 25.0 : 0;

        detail = detail with
        {
            ScoreReturn = Math.Round(scoreReturn, 1),
            ScoreTrend = scoreTrend,
            ScoreBreakout = scoreBreakout,
            ScoreVolume = scoreVolume,
        };

        return detail;
    }

    // ═══════════════════════════════════════
    // Universe List (Pipeline 팝업)
    // ═══════════════════════════════════════

    public async Task<List<SwingUniverseItem>> GetUniverseListAsync(int limit = 300)
    {
        var items = new List<SwingUniverseItem>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            SELECT symbol, company_name, sector, market_cap, index_member
            FROM swing_universe WHERE is_active = true
            ORDER BY market_cap DESC NULLS LAST LIMIT @limit", conn);
        cmd.Parameters.AddWithValue("@limit", limit);
        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            items.Add(new SwingUniverseItem(
                Symbol: r.GetString(0),
                CompanyName: r.IsDBNull(1) ? null : r.GetString(1),
                Sector: r.IsDBNull(2) ? null : r.GetString(2),
                MarketCap: r.IsDBNull(3) ? null : r.GetDecimal(3),
                IndexMember: r.IsDBNull(4) ? null : r.GetString(4)
            ));
        }
        return items;
    }

    // ═══════════════════════════════════════
    // Indicator List (Pipeline 팝업)
    // ═══════════════════════════════════════

    public async Task<List<SwingIndicatorRow>> GetIndicatorListAsync(int limit = 300)
    {
        var items = new List<SwingIndicatorRow>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            SELECT symbol, close, sma_50, sma_200, return_20d_rank,
                   volume_ratio, trend_aligned, volume_surge, time
            FROM swing_indicators
            ORDER BY return_20d_rank DESC NULLS LAST LIMIT @limit", conn);
        cmd.Parameters.AddWithValue("@limit", limit);
        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            items.Add(new SwingIndicatorRow(
                Symbol: r.GetString(0),
                Close: r.IsDBNull(1) ? null : r.GetDecimal(1),
                Sma50: r.IsDBNull(2) ? null : r.GetDecimal(2),
                Sma200: r.IsDBNull(3) ? null : r.GetDecimal(3),
                Return20dRank: r.IsDBNull(4) ? null : (double)r.GetDecimal(4),
                VolumeRatio: r.IsDBNull(5) ? null : (double)r.GetDecimal(5),
                TrendAligned: !r.IsDBNull(6) && r.GetBoolean(6),
                VolumeSurge: !r.IsDBNull(7) && r.GetBoolean(7),
                Time: r.GetDateTime(8)
            ));
        }
        return items;
    }

    // ═══════════════════════════════════════
    // Pipeline Status Queries
    // ═══════════════════════════════════════

    public async Task<int> GetUniverseCountAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT count(*) FROM swing_universe", conn);
        var result = await cmd.ExecuteScalarAsync();
        return Convert.ToInt32(result);
    }

    public async Task<(int Count, DateTime? LastUpdated)> GetIndicatorStatusAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT count(*), max(time) FROM swing_indicators", conn);
        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return (0, null);
        var count = r.IsDBNull(0) ? 0 : Convert.ToInt32(r.GetValue(0));
        var lastUpdated = r.IsDBNull(1) ? (DateTime?)null : r.GetDateTime(1);
        return (count, lastUpdated);
    }

    public async Task<Dictionary<string, int>> GetSignalCountsByStatusAsync()
    {
        var counts = new Dictionary<string, int>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT status, count(*)::int FROM swing_signals GROUP BY status", conn);
        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            counts[r.GetString(0)] = r.GetInt32(1);
        }
        return counts;
    }

    // ═══════════════════════════════════════
    // Health Check
    // ═══════════════════════════════════════

    public async Task<bool> HealthCheckAsync()
    {
        try
        {
            await using var conn = new NpgsqlConnection(_connStr);
            await conn.OpenAsync();
            await using var cmd = new NpgsqlCommand("SELECT 1", conn);
            await cmd.ExecuteScalarAsync();
            return true;
        }
        catch
        {
            return false;
        }
    }
}
