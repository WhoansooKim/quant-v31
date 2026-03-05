using Npgsql;
using QuantDashboard.Models;

namespace QuantDashboard.Services;

/// <summary>
/// PostgreSQL + TimescaleDB 직접 조회 서비스 (Npgsql Raw SQL)
/// Entity Framework 미사용 — TimescaleDB 전용 함수 최대 활용
/// </summary>
public class PostgresService
{
    private readonly string _connStr;
    private readonly ILogger<PostgresService> _logger;

    public PostgresService(string connectionString, ILogger<PostgresService> logger)
    {
        _connStr = connectionString;
        _logger = logger;
    }

    // ═══════════════════════════════════════
    // 레짐
    // ═══════════════════════════════════════

    public async Task<RegimeState?> GetCurrentRegimeAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT regime, bull_prob, sideways_prob, bear_prob,
                   confidence, previous_regime, is_transition, detected_at
            FROM regime_history
            ORDER BY detected_at DESC LIMIT 1", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new RegimeState(
            Regime: r.GetString(0),
            BullProb: r.GetDouble(1),
            SidewaysProb: r.GetDouble(2),
            BearProb: r.GetDouble(3),
            Confidence: r.GetDouble(4),
            PreviousRegime: r.IsDBNull(5) ? null : r.GetString(5),
            IsTransition: r.GetBoolean(6),
            DetectedAt: r.GetDateTime(7)
        );
    }

    public async Task<List<RegimeState>> GetRegimeHistoryAsync(int days = 90)
    {
        var results = new List<RegimeState>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT regime, bull_prob, sideways_prob, bear_prob,
                   confidence, previous_regime, is_transition, detected_at
            FROM regime_history
            WHERE detected_at > now() - interval '{days} days'
            ORDER BY detected_at DESC", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new RegimeState(
                r.GetString(0), r.GetDouble(1), r.GetDouble(2), r.GetDouble(3),
                r.GetDouble(4), r.IsDBNull(5) ? null : r.GetString(5),
                r.GetBoolean(6), r.GetDateTime(7)
            ));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // Kill Switch
    // ═══════════════════════════════════════

    public async Task<KillSwitchState?> GetKillSwitchAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT from_level, to_level, current_mdd, portfolio_value,
                   exposure_limit, cooldown_until, event_time
            FROM kill_switch_log
            ORDER BY event_time DESC LIMIT 1", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new KillSwitchState(
            FromLevel: r.GetString(0),
            ToLevel: r.GetString(1),
            CurrentMdd: r.GetDouble(2),
            PortfolioValue: r.GetDouble(3),
            ExposureLimit: r.GetDouble(4),
            CooldownUntil: r.IsDBNull(5) ? null : r.GetDateTime(5),
            EventTime: r.GetDateTime(6)
        );
    }

    public async Task<List<KillSwitchState>> GetKillSwitchHistoryAsync(int days = 90)
    {
        var results = new List<KillSwitchState>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT from_level, to_level, current_mdd, portfolio_value,
                   exposure_limit, cooldown_until, event_time
            FROM kill_switch_log
            WHERE event_time > now() - interval '{days} days'
            ORDER BY event_time DESC", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new KillSwitchState(
                r.GetString(0), r.GetString(1), r.GetDouble(2), r.GetDouble(3),
                r.GetDouble(4), r.IsDBNull(5) ? null : r.GetDateTime(5), r.GetDateTime(6)
            ));
        }
        return results;
    }

    public async Task InsertKillSwitchLogAsync(string fromLevel, string toLevel,
        double currentMdd, double portfolioValue, double exposureLimit)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            INSERT INTO kill_switch_log
                (from_level, to_level, current_mdd, portfolio_value, exposure_limit)
            VALUES (@from, @to, @mdd, @pv, @exp)", conn);
        cmd.Parameters.AddWithValue("from", fromLevel);
        cmd.Parameters.AddWithValue("to", toLevel);
        cmd.Parameters.AddWithValue("mdd", currentMdd);
        cmd.Parameters.AddWithValue("pv", portfolioValue);
        cmd.Parameters.AddWithValue("exp", exposureLimit);

        await cmd.ExecuteNonQueryAsync();
    }

    // ═══════════════════════════════════════
    // 포트폴리오 스냅샷
    // ═══════════════════════════════════════

    public async Task<List<DailySnapshot>> GetPerformanceAsync(int days = 30)
    {
        var results = new List<DailySnapshot>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT time, total_value, cash_value, daily_return, cumulative_return,
                   sharpe_ratio, max_drawdown, vol_scale, regime,
                   regime_confidence, kill_level, exposure_limit
            FROM portfolio_snapshots
            WHERE time > now() - interval '{days} days'
            ORDER BY time DESC", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new DailySnapshot(
                Time: r.GetDateTime(0),
                TotalValue: r.IsDBNull(1) ? 0m : r.GetDecimal(1),
                CashValue: r.IsDBNull(2) ? null : r.GetDecimal(2),
                DailyReturn: r.IsDBNull(3) ? null : r.GetDouble(3),
                CumulativeReturn: r.IsDBNull(4) ? null : r.GetDouble(4),
                Sharpe: r.IsDBNull(5) ? null : r.GetDouble(5),
                MaxDrawdown: r.IsDBNull(6) ? 0 : r.GetDouble(6),
                VolScale: r.IsDBNull(7) ? null : r.GetDouble(7),
                Regime: r.IsDBNull(8) ? "unknown" : r.GetString(8),
                RegimeConfidence: r.IsDBNull(9) ? null : r.GetDouble(9),
                KillLevel: r.IsDBNull(10) ? "NORMAL" : r.GetString(10),
                ExposureLimit: r.IsDBNull(11) ? null : r.GetDouble(11)
            ));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // 거래 기록
    // ═══════════════════════════════════════

    public async Task<List<TradeRecord>> GetRecentTradesAsync(int limit = 50)
    {
        var results = new List<TradeRecord>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT trade_id, order_id, symbol, strategy, side, qty, price,
                   regime, kill_level, executed_at, is_paper
            FROM trades
            ORDER BY executed_at DESC
            LIMIT {limit}", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new TradeRecord(
                TradeId: r.GetInt64(0),
                OrderId: r.IsDBNull(1) ? null : r.GetString(1),
                Symbol: r.GetString(2),
                Strategy: r.GetString(3),
                Side: r.GetString(4),
                Qty: r.GetDecimal(5),
                Price: r.GetDecimal(6),
                Regime: r.GetString(7),
                KillLevel: r.GetString(8),
                ExecutedAt: r.GetDateTime(9),
                IsPaper: r.GetBoolean(10)
            ));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // 전략 성과
    // ═══════════════════════════════════════

    public async Task<List<StrategyPerf>> GetStrategyPerfAsync(int days = 30)
    {
        var results = new List<StrategyPerf>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT time, strategy, daily_return, allocation, regime,
                   signal_count, win_rate
            FROM strategy_performance
            WHERE time > now() - interval '{days} days'
            ORDER BY time DESC", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new StrategyPerf(
                Time: r.GetDateTime(0),
                Strategy: r.GetString(1),
                DailyReturn: r.GetDouble(2),
                Allocation: r.GetDouble(3),
                Regime: r.GetString(4),
                SignalCount: r.GetInt32(5),
                WinRate: r.IsDBNull(6) ? null : r.GetDouble(6)
            ));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // 시그널 로그
    // ═══════════════════════════════════════

    public async Task<List<SignalRecord>> GetRecentSignalsAsync(int limit = 100)
    {
        var results = new List<SignalRecord>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT time, symbol, direction, strength, strategy, regime
            FROM signal_log
            ORDER BY time DESC
            LIMIT {limit}", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new SignalRecord(
                Time: r.GetDateTime(0),
                Symbol: r.GetString(1),
                Direction: r.GetString(2),
                Strength: r.GetDouble(3),
                Strategy: r.GetString(4),
                Regime: r.GetString(5)
            ));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // 센티먼트 히트맵 (TimescaleDB time_bucket)
    // ═══════════════════════════════════════

    public async Task<List<SentimentPoint>> GetSentimentHeatmapAsync(int days = 30, string bucket = "1 day")
    {
        var results = new List<SentimentPoint>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        // bucket은 고정 값 셋 중 하나이므로 SQL injection 방지
        var safeBucket = bucket switch
        {
            "1 hour" => "1 hour",
            "4 hours" => "4 hours",
            "1 week" => "1 week",
            _ => "1 day",
        };

        await using var cmd = new NpgsqlCommand($@"
            SELECT time_bucket('{safeBucket}', time) AS day,
                   symbol,
                   AVG(hybrid_score) AS avg_score,
                   COUNT(*)::int AS headline_count
            FROM sentiment_scores
            WHERE time > now() - interval '{days} days'
            GROUP BY day, symbol
            ORDER BY day DESC, avg_score DESC", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new SentimentPoint(
                Day: r.GetDateTime(0),
                Symbol: r.GetString(1),
                AvgScore: r.GetDouble(2),
                HeadlineCount: r.GetInt32(3)
            ));
        }
        return results;
    }

    public async Task<List<SentimentScoreRow>> GetSentimentScoresRawAsync(int days = 1, int limit = 200)
    {
        var results = new List<SentimentScoreRow>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT time, symbol, hybrid_score, source
            FROM sentiment_scores
            WHERE time > now() - interval '{days} days'
            ORDER BY time DESC
            LIMIT {limit}", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new SentimentScoreRow(
                Time: r.GetDateTime(0),
                Symbol: r.IsDBNull(1) ? "" : r.GetString(1),
                Score: r.IsDBNull(2) ? 0 : r.GetDouble(2),
                Headline: r.IsDBNull(3) ? null : r.GetString(3)
            ));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // 백테스트
    // ═══════════════════════════════════════

    public async Task<List<BacktestRun>> GetBacktestRunsAsync(int limit = 20)
    {
        var results = new List<BacktestRun>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT run_id, name, run_type, status, started_at, finished_at,
                   summary::text
            FROM backtest_runs
            ORDER BY started_at DESC LIMIT {limit}", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new BacktestRun(
                RunId: r.GetInt32(0),
                Name: r.GetString(1),
                RunType: r.GetString(2),
                Status: r.GetString(3),
                StartedAt: r.GetDateTime(4),
                FinishedAt: r.IsDBNull(5) ? null : r.GetDateTime(5),
                Summary: r.IsDBNull(6) ? null : r.GetString(6)
            ));
        }
        return results;
    }

    public async Task<List<WalkForwardFoldResult>> GetLatestWalkForwardAsync()
    {
        var results = new List<WalkForwardFoldResult>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT wf.fold_num, wf.train_start, wf.train_end,
                   wf.test_start, wf.test_end,
                   wf.is_sharpe, wf.oos_sharpe, wf.oos_cagr,
                   wf.oos_mdd, wf.oos_calmar
            FROM walk_forward_results wf
            JOIN (SELECT run_id FROM backtest_runs
                  WHERE run_type = 'walk_forward' AND status = 'completed'
                  ORDER BY finished_at DESC LIMIT 1) latest
            ON wf.run_id = latest.run_id
            ORDER BY wf.fold_num", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new WalkForwardFoldResult(
                FoldNum: r.GetInt32(0),
                TrainStart: r.GetDateTime(1),
                TrainEnd: r.GetDateTime(2),
                TestStart: r.GetDateTime(3),
                TestEnd: r.GetDateTime(4),
                IsSharpe: r.GetDouble(5),
                OosSharpe: r.GetDouble(6),
                OosCagr: r.GetDouble(7),
                OosMdd: r.GetDouble(8),
                OosCalmar: r.GetDouble(9)
            ));
        }
        return results;
    }

    public async Task<MonteCarloResultRow?> GetLatestMonteCarloAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT mc.n_simulations, mc.median_cagr, mc.p5_cagr, mc.p95_cagr,
                   mc.median_sharpe, mc.p5_sharpe, mc.p95_sharpe,
                   mc.median_mdd, mc.prob_negative, mc.prob_mdd_over_20
            FROM monte_carlo_results mc
            JOIN (SELECT run_id FROM backtest_runs
                  WHERE run_type = 'monte_carlo' AND status = 'completed'
                  ORDER BY finished_at DESC LIMIT 1) latest
            ON mc.run_id = latest.run_id", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new MonteCarloResultRow(
            NSims: r.GetInt32(0),
            MedianCagr: r.GetDouble(1),
            P5Cagr: r.GetDouble(2),
            P95Cagr: r.GetDouble(3),
            MedianSharpe: r.GetDouble(4),
            P5Sharpe: r.GetDouble(5),
            P95Sharpe: r.GetDouble(6),
            MedianMdd: r.GetDouble(7),
            ProbNegative: r.GetDouble(8),
            ProbMddOver20: r.GetDouble(9)
        );
    }

    public async Task<List<StressTestResultRow>> GetLatestStressTestAsync()
    {
        var results = new List<StressTestResultRow>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT rs.scenario, rs.period_start, rs.period_end,
                   rs.total_return, rs.max_drawdown, rs.sharpe,
                   rs.kill_triggered, rs.kill_level_reached,
                   rs.regime_accuracy, rs.false_positive_rate,
                   rs.detection_lag_days
            FROM regime_stress_results rs
            JOIN (SELECT run_id FROM backtest_runs
                  WHERE run_type = 'regime_stress' AND status = 'completed'
                  ORDER BY finished_at DESC LIMIT 1) latest
            ON rs.run_id = latest.run_id", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new StressTestResultRow(
                Scenario: r.GetString(0),
                PeriodStart: r.GetDateTime(1),
                PeriodEnd: r.GetDateTime(2),
                TotalReturn: r.GetDouble(3),
                MaxDrawdown: r.GetDouble(4),
                Sharpe: r.GetDouble(5),
                KillTriggered: r.GetBoolean(6),
                KillLevelReached: r.GetString(7),
                RegimeAccuracy: r.GetDouble(8),
                FalsePositiveRate: r.GetDouble(9),
                DetectionLagDays: r.GetInt32(10)
            ));
        }
        return results;
    }

    public async Task<DsrResultRow?> GetLatestDsrAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT d.raw_sharpe, d.dsr_score, d.dsr_pvalue,
                   d.n_trials, d.skewness, d.kurtosis, d.passed
            FROM dsr_results d
            JOIN (SELECT run_id FROM backtest_runs
                  WHERE run_type = 'dsr' AND status = 'completed'
                  ORDER BY finished_at DESC LIMIT 1) latest
            ON d.run_id = latest.run_id", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new DsrResultRow(
            RawSharpe: r.GetDouble(0),
            DsrScore: r.GetDouble(1),
            DsrPvalue: r.GetDouble(2),
            NTrials: r.GetInt32(3),
            Skewness: r.GetDouble(4),
            Kurtosis: r.GetDouble(5),
            Passed: r.GetBoolean(6)
        );
    }

    public async Task<GoStopDecision?> GetLatestGoStopAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT decision, criteria::text, notes, decided_by, time
            FROM go_stop_log
            ORDER BY time DESC LIMIT 1", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new GoStopDecision(
            Decision: r.GetString(0),
            Criteria: r.IsDBNull(1) ? null : r.GetString(1),
            Notes: r.IsDBNull(2) ? null : r.GetString(2),
            DecidedBy: r.IsDBNull(3) ? null : r.GetString(3),
            DecidedAt: r.GetDateTime(4)
        );
    }

    // ═══════════════════════════════════════
    // 시스템 종합 상태
    // ═══════════════════════════════════════

    public async Task<SystemStatus> GetSystemStatusAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT
                (SELECT COUNT(*) FROM backtest_runs)::int,
                (SELECT COUNT(*) FROM portfolio_snapshots)::int,
                (SELECT COUNT(*) FROM trades)::int,
                (SELECT COUNT(*) FROM signal_log)::int,
                (SELECT regime FROM regime_history ORDER BY detected_at DESC LIMIT 1),
                (SELECT to_level FROM kill_switch_log ORDER BY event_time DESC LIMIT 1),
                (SELECT decision FROM go_stop_log ORDER BY time DESC LIMIT 1),
                (SELECT time FROM portfolio_snapshots ORDER BY time DESC LIMIT 1),
                (SELECT detected_at FROM regime_history ORDER BY detected_at DESC LIMIT 1),
                (SELECT time FROM go_stop_log ORDER BY time DESC LIMIT 1)
        ", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync())
            return new SystemStatus(true, true, 0, 0, 0, 0, null, null, null, null, null, null);

        return new SystemStatus(
            DbConnected: true,
            EngineHealthy: true,
            BacktestRunCount: r.GetInt32(0),
            SnapshotCount: r.GetInt32(1),
            TradeCount: r.GetInt32(2),
            SignalCount: r.GetInt32(3),
            LatestRegime: r.IsDBNull(4) ? null : r.GetString(4),
            LatestKillLevel: r.IsDBNull(5) ? null : r.GetString(5),
            LatestGoStop: r.IsDBNull(6) ? null : r.GetString(6),
            LatestSnapshotTime: r.IsDBNull(7) ? null : r.GetDateTime(7),
            LatestRegimeTime: r.IsDBNull(8) ? null : r.GetDateTime(8),
            LatestGoStopTime: r.IsDBNull(9) ? null : r.GetDateTime(9)
        );
    }

    public async Task<List<GoStopDecision>> GetGoStopHistoryAsync(int limit = 10)
    {
        var results = new List<GoStopDecision>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT decision, criteria::text, notes, decided_by, time
            FROM go_stop_log
            ORDER BY time DESC LIMIT {limit}", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new GoStopDecision(
                r.GetString(0),
                r.IsDBNull(1) ? null : r.GetString(1),
                r.IsDBNull(2) ? null : r.GetString(2),
                r.IsDBNull(3) ? null : r.GetString(3),
                r.GetDateTime(4)
            ));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // Admin — 파이프라인 로그
    // ═══════════════════════════════════════

    public async Task<List<PipelineLogEntry>> GetPipelineLogsAsync(int limit = 50)
    {
        var results = new List<PipelineLogEntry>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT time, job_type, status, duration_sec,
                   details::text, error_msg
            FROM pipeline_log
            ORDER BY time DESC
            LIMIT {limit}", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new PipelineLogEntry(
                Time: r.GetDateTime(0),
                JobType: r.GetString(1),
                Status: r.GetString(2),
                DurationSec: r.IsDBNull(3) ? null : r.GetDouble(3),
                Details: r.IsDBNull(4) ? null : r.GetString(4),
                ErrorMsg: r.IsDBNull(5) ? null : r.GetString(5)
            ));
        }
        return results;
    }

    public async Task<DataCollectionStatus> GetDataCollectionStatusAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT
                (SELECT MAX(time) FROM daily_prices),
                (SELECT COUNT(*)::int FROM symbols WHERE is_active = true),
                (SELECT COUNT(DISTINCT symbol)::int FROM daily_prices
                 WHERE time > now() - interval '3 days')
        ", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync())
            return new DataCollectionStatus(null, 0, 0);

        return new DataCollectionStatus(
            LatestDataDate: r.IsDBNull(0) ? null : r.GetDateTime(0),
            ActiveSymbols: r.GetInt32(1),
            RecentSymbols: r.GetInt32(2)
        );
    }

    public async Task<SentimentScanStatus> GetSentimentScanStatusAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT
                (SELECT COUNT(*)::int FROM sentiment_scores
                 WHERE time > now() - interval '24 hours'),
                (SELECT MAX(time) FROM sentiment_scores)
        ", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync())
            return new SentimentScanStatus(0, null);

        return new SentimentScanStatus(
            Recent24hCount: r.GetInt32(0),
            LastScanTime: r.IsDBNull(1) ? null : r.GetDateTime(1)
        );
    }

    public async Task<string?> GetLatestPipelineDetailAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT details::text FROM pipeline_log
            WHERE job_type = 'daily_pipeline' AND status = 'completed'
                  AND details IS NOT NULL
            ORDER BY time DESC LIMIT 1", conn);

        var result = await cmd.ExecuteScalarAsync();
        return result as string;
    }

    // ═══════════════════════════════════════
    // 심볼 → 거래소 매핑
    // ═══════════════════════════════════════

    public async Task<Dictionary<string, string>> GetSymbolExchangeMapAsync()
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(
            "SELECT ticker, exchange FROM symbols WHERE is_active = true AND exchange IS NOT NULL", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            map[r.GetString(0)] = r.GetString(1);
        }
        return map;
    }

    // ═══════════════════════════════════════
    // 티커바 (주요 지수)
    // ═══════════════════════════════════════

    public async Task<List<TickerBarItem>> GetTickerBarDataAsync()
    {
        var results = new List<TickerBarItem>();
        var tickers = new[] { "SPY", "QQQ", "IWM", "DIA", "VIX" };

        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        foreach (var sym in tickers)
        {
            try
            {
                await using var cmd = new NpgsqlCommand(@"
                    SELECT close FROM daily_prices
                    WHERE symbol = @sym
                    ORDER BY time DESC LIMIT 2", conn);
                cmd.Parameters.AddWithValue("sym", sym);

                var rows = new List<double>();
                await using var r = await cmd.ExecuteReaderAsync();
                while (await r.ReadAsync())
                    rows.Add(r.GetDouble(0));

                if (rows.Count >= 2)
                {
                    var price = rows[0];
                    var prev = rows[1];
                    var chg = prev != 0 ? (price - prev) / prev * 100 : 0;
                    results.Add(new TickerBarItem(sym, price, chg));
                }
                else if (rows.Count == 1)
                {
                    results.Add(new TickerBarItem(sym, rows[0], 0));
                }
            }
            catch { }
        }
        return results;
    }

    // ═══════════════════════════════════════
    // 투자금 설정
    // ═══════════════════════════════════════

    public async Task<decimal> GetInitialCapitalAsync(int userId)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT initial_capital FROM user_settings WHERE user_id = @uid", conn);
        cmd.Parameters.AddWithValue("uid", userId);

        var result = await cmd.ExecuteScalarAsync();
        return result is decimal d ? d : 100000m;
    }

    public async Task UpdateInitialCapitalAsync(int userId, decimal amount)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            INSERT INTO user_settings (user_id, initial_capital, updated_at)
            VALUES (@uid, @amt, now())
            ON CONFLICT (user_id) DO UPDATE
            SET initial_capital = @amt, updated_at = now()", conn);
        cmd.Parameters.AddWithValue("uid", userId);
        cmd.Parameters.AddWithValue("amt", amount);

        await cmd.ExecuteNonQueryAsync();
    }

    // ═══════════════════════════════════════
    // 포트폴리오 보유 포지션
    // ═══════════════════════════════════════

    public async Task<List<PortfolioHolding>> GetPortfolioHoldingsAsync()
    {
        var results = new List<PortfolioHolding>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT symbol, strategy,
                   SUM(CASE WHEN side = 'buy' THEN qty ELSE -qty END) AS net_qty,
                   CASE WHEN SUM(CASE WHEN side = 'buy' THEN qty ELSE 0 END) > 0
                        THEN SUM(CASE WHEN side = 'buy' THEN qty * price ELSE 0 END)
                             / SUM(CASE WHEN side = 'buy' THEN qty ELSE 0 END)
                        ELSE 0 END AS avg_price,
                   SUM(CASE WHEN side = 'buy' THEN qty * price ELSE -qty * price END) AS total_cost,
                   MAX(executed_at) AS last_trade_at
            FROM trades
            GROUP BY symbol, strategy
            HAVING SUM(CASE WHEN side = 'buy' THEN qty ELSE -qty END) > 0
            ORDER BY last_trade_at DESC", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new PortfolioHolding(
                Symbol: r.GetString(0),
                Strategy: r.GetString(1),
                NetQty: r.GetDecimal(2),
                AvgPrice: r.GetDecimal(3),
                TotalCost: r.GetDecimal(4),
                LastTradeAt: r.GetDateTime(5)
            ));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // 최신 전략 배분
    // ═══════════════════════════════════════

    public async Task<List<StrategyAllocation>> GetLatestStrategyAllocationsAsync()
    {
        var results = new List<StrategyAllocation>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT DISTINCT ON (strategy) strategy, allocation::float8, regime, time
            FROM strategy_performance
            ORDER BY strategy, time DESC", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new StrategyAllocation(
                Strategy: r.GetString(0),
                Allocation: r.GetDouble(1),
                Regime: r.GetString(2),
                Time: r.GetDateTime(3)
            ));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // 신호 분포 (5단계)
    // ═══════════════════════════════════════

    public async Task<List<SignalDistribution>> GetSignalDistributionAsync()
    {
        var results = new List<SignalDistribution>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT category, COUNT(*)::int AS cnt FROM (
                SELECT CASE
                    WHEN strength >  0.7 THEN 'Strong Buy'
                    WHEN strength >  0.3 THEN 'Buy'
                    WHEN strength > -0.3 THEN 'Hold'
                    WHEN strength > -0.7 THEN 'Sell'
                    ELSE 'Strong Sell'
                END AS category
                FROM signal_log
                WHERE time > now() - interval '7 days'
            ) sub
            GROUP BY category
            ORDER BY CASE category
                WHEN 'Strong Buy'  THEN 1
                WHEN 'Buy'         THEN 2
                WHEN 'Hold'        THEN 3
                WHEN 'Sell'        THEN 4
                WHEN 'Strong Sell' THEN 5
            END", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new SignalDistribution(r.GetString(0), r.GetInt32(1)));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // Top / Bottom 종목
    // ═══════════════════════════════════════

    public async Task<(List<RankedStock> Top, List<RankedStock> Bottom)> GetTopBottomStocksAsync(int topN = 5)
    {
        var top = new List<RankedStock>();
        var bottom = new List<RankedStock>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        // Top N by strength
        await using var cmdTop = new NpgsqlCommand($@"
            SELECT DISTINCT ON (s.symbol) s.symbol, COALESCE(sym.sector, 'N/A'),
                   s.strength::float8, (s.strength * 100)::float8, s.direction
            FROM signal_log s
            LEFT JOIN symbols sym ON sym.ticker = s.symbol
            WHERE s.time > now() - interval '7 days'
            ORDER BY s.symbol, s.time DESC", conn);

        var all = new List<RankedStock>();
        await using var r = await cmdTop.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            all.Add(new RankedStock(
                r.GetString(0), r.GetString(1), r.GetDouble(2),
                r.GetDouble(3), r.GetString(4)));
        }

        top = all.OrderByDescending(x => x.Score).Take(topN).ToList();
        bottom = all.OrderBy(x => x.Score).Take(topN).ToList();
        return (top, bottom);
    }

    // ═══════════════════════════════════════
    // 섹터별 스코어
    // ═══════════════════════════════════════

    public async Task<List<SectorScore>> GetSectorScoresAsync()
    {
        var results = new List<SectorScore>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            WITH latest AS (
                SELECT DISTINCT ON (s.symbol) s.symbol, s.strength
                FROM signal_log s
                WHERE s.time > now() - interval '7 days'
                ORDER BY s.symbol, s.time DESC
            )
            SELECT COALESCE(sym.sector, 'N/A') AS sector,
                   AVG(l.strength)::float8 AS avg_score,
                   COUNT(*)::int AS cnt
            FROM latest l
            LEFT JOIN symbols sym ON sym.ticker = l.symbol
            GROUP BY sym.sector
            ORDER BY avg_score DESC", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            results.Add(new SectorScore(r.GetString(0), r.GetDouble(1), r.GetInt32(2)));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // 종목 상세 (16개 팩터)
    // ═══════════════════════════════════════

    public async Task<SymbolDetail?> GetSymbolDetailAsync(string symbol)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            WITH price_now AS (
                SELECT close::float8 AS price FROM daily_prices
                WHERE symbol = @sym ORDER BY time DESC LIMIT 1
            ),
            price_1m AS (
                SELECT close::float8 AS close FROM daily_prices
                WHERE symbol = @sym AND time <= now() - interval '1 month'
                ORDER BY time DESC LIMIT 1
            ),
            price_3m AS (
                SELECT close::float8 AS close FROM daily_prices
                WHERE symbol = @sym AND time <= now() - interval '3 months'
                ORDER BY time DESC LIMIT 1
            ),
            price_6m AS (
                SELECT close::float8 AS close FROM daily_prices
                WHERE symbol = @sym AND time <= now() - interval '6 months'
                ORDER BY time DESC LIMIT 1
            ),
            price_12m AS (
                SELECT close::float8 AS close FROM daily_prices
                WHERE symbol = @sym AND time <= now() - interval '12 months'
                ORDER BY time DESC LIMIT 1
            ),
            sig AS (
                SELECT strength::float8, direction FROM signal_log
                WHERE symbol = @sym ORDER BY time DESC LIMIT 1
            ),
            fund AS (
                SELECT eps::float8, roe::float8, revenue_growth::float8,
                       debt_to_equity::float8, free_cashflow::float8, extra
                FROM fundamentals
                WHERE ticker = @sym
                ORDER BY report_date DESC LIMIT 1
            ),
            sma_data AS (
                SELECT
                    AVG(c) FILTER (WHERE rn <= 50)  AS sma50,
                    AVG(c) FILTER (WHERE rn <= 200) AS sma200
                FROM (
                    SELECT close::float8 AS c,
                           ROW_NUMBER() OVER (ORDER BY time DESC) AS rn
                    FROM daily_prices WHERE symbol = @sym
                ) sub WHERE rn <= 200
            ),
            rsi_data AS (
                SELECT CASE
                    WHEN SUM(CASE WHEN diff < 0 THEN ABS(diff) ELSE 0 END) > 0
                    THEN 100.0 - 100.0 / (1.0 +
                         SUM(CASE WHEN diff > 0 THEN diff ELSE 0 END) /
                         SUM(CASE WHEN diff < 0 THEN ABS(diff) ELSE 0 END))
                    ELSE 100.0 END AS rsi
                FROM (
                    SELECT (close - LAG(close) OVER (ORDER BY time))::float8 AS diff
                    FROM daily_prices WHERE symbol = @sym
                    ORDER BY time DESC LIMIT 15
                ) sub WHERE diff IS NOT NULL
            ),
            macd_data AS (
                SELECT
                    (AVG(c) FILTER (WHERE rn <= 12) -
                     AVG(c) FILTER (WHERE rn <= 26)) AS macd
                FROM (
                    SELECT close::float8 AS c,
                           ROW_NUMBER() OVER (ORDER BY time DESC) AS rn
                    FROM daily_prices WHERE symbol = @sym
                ) sub WHERE rn <= 26
            )
            SELECT
                @sym AS symbol,
                COALESCE((SELECT sector FROM symbols WHERE ticker = @sym), 'N/A'),
                (SELECT price FROM price_now),
                CASE WHEN (SELECT close FROM price_1m) > 0
                     THEN ((SELECT price FROM price_now) - (SELECT close FROM price_1m)) / (SELECT close FROM price_1m) * 100
                END,
                CASE WHEN (SELECT close FROM price_3m) > 0
                     THEN ((SELECT price FROM price_now) - (SELECT close FROM price_3m)) / (SELECT close FROM price_3m) * 100
                END,
                CASE WHEN (SELECT close FROM price_6m) > 0
                     THEN ((SELECT price FROM price_now) - (SELECT close FROM price_6m)) / (SELECT close FROM price_6m) * 100
                END,
                CASE WHEN (SELECT close FROM price_12m) > 0
                     THEN ((SELECT price FROM price_now) - (SELECT close FROM price_12m)) / (SELECT close FROM price_12m) * 100
                END,
                /* PE = price / eps */
                CASE WHEN (SELECT eps FROM fund) IS NOT NULL AND (SELECT eps FROM fund) != 0
                     THEN (SELECT price FROM price_now) / (SELECT eps FROM fund) END,
                /* PB (from extra JSONB) */
                (SELECT (extra->>'pb')::float8 FROM fund),
                /* PS (from extra JSONB) */
                (SELECT (extra->>'ps')::float8 FROM fund),
                /* ROE (percentage) */
                (SELECT roe * 100 FROM fund),
                /* EPS Growth (from extra JSONB, percentage) */
                (SELECT (extra->>'eps_growth')::float8 FROM fund),
                /* Revenue Growth (percentage) */
                (SELECT revenue_growth * 100 FROM fund),
                /* Debt Ratio */
                (SELECT debt_to_equity FROM fund),
                /* FCF */
                (SELECT free_cashflow FROM fund),
                /* RSI */
                (SELECT rsi FROM rsi_data),
                /* MACD */
                (SELECT macd FROM macd_data),
                /* SMA50 */
                (SELECT sma50 FROM sma_data),
                /* SMA200 */
                (SELECT sma200 FROM sma_data),
                (SELECT strength FROM sig),
                (SELECT direction FROM sig)
        ", conn);
        cmd.Parameters.AddWithValue("sym", symbol);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new SymbolDetail(
            Symbol: r.GetString(0),
            Sector: r.GetString(1),
            Price: r.IsDBNull(2) ? null : r.GetDouble(2),
            Change1M: r.IsDBNull(3) ? null : r.GetDouble(3),
            Change3M: r.IsDBNull(4) ? null : r.GetDouble(4),
            Change6M: r.IsDBNull(5) ? null : r.GetDouble(5),
            Change12M: r.IsDBNull(6) ? null : r.GetDouble(6),
            PE: r.IsDBNull(7) ? null : r.GetDouble(7),
            PB: r.IsDBNull(8) ? null : r.GetDouble(8),
            PS: r.IsDBNull(9) ? null : r.GetDouble(9),
            ROE: r.IsDBNull(10) ? null : r.GetDouble(10),
            EpsGrowth: r.IsDBNull(11) ? null : r.GetDouble(11),
            RevenueGrowth: r.IsDBNull(12) ? null : r.GetDouble(12),
            DebtRatio: r.IsDBNull(13) ? null : r.GetDouble(13),
            FCF: r.IsDBNull(14) ? null : r.GetDouble(14),
            RSI: r.IsDBNull(15) ? null : r.GetDouble(15),
            MACD: r.IsDBNull(16) ? null : r.GetDouble(16),
            SMA50: r.IsDBNull(17) ? null : r.GetDouble(17),
            SMA200: r.IsDBNull(18) ? null : r.GetDouble(18),
            QuantScore: r.IsDBNull(19) ? null : r.GetDouble(19),
            Signal: r.IsDBNull(20) ? null : r.GetString(20)
        );
    }

    // ═══════════════════════════════════════
    // SPY 벤치마크
    // ═══════════════════════════════════════

    public async Task<List<BenchmarkPoint>> GetSpyBenchmarkAsync(int days)
    {
        var results = new List<BenchmarkPoint>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT time, close::float8 FROM daily_prices
            WHERE symbol = 'SPY' AND time > now() - interval '{days} days'
            ORDER BY time ASC", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        double? firstClose = null;
        while (await r.ReadAsync())
        {
            var close = r.GetDouble(1);
            firstClose ??= close;
            var cumReturn = firstClose.Value > 0 ? (close / firstClose.Value - 1.0) * 100 : 0;
            results.Add(new BenchmarkPoint(r.GetDateTime(0), cumReturn));
        }
        return results;
    }

    // ═══════════════════════════════════════
    // 시장 감성 지수
    // ═══════════════════════════════════════

    public async Task<MarketSentiment> GetMarketSentimentAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            SELECT
                COALESCE(AVG(hybrid_score)::float8, 0),
                COALESCE(SUM(CASE WHEN hybrid_score >  0.3 THEN 1 ELSE 0 END)::int, 0),
                COALESCE(SUM(CASE WHEN hybrid_score < -0.3 THEN 1 ELSE 0 END)::int, 0),
                COALESCE(SUM(CASE WHEN hybrid_score BETWEEN -0.3 AND 0.3 THEN 1 ELSE 0 END)::int, 0),
                COALESCE(COUNT(*)::int, 0)
            FROM sentiment_scores
            WHERE time > now() - interval '24 hours'", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync())
            return new MarketSentiment(0, 0, 0, 0, 0);

        return new MarketSentiment(
            AvgScore: r.GetDouble(0),
            PositiveCount: r.GetInt32(1),
            NegativeCount: r.GetInt32(2),
            NeutralCount: r.GetInt32(3),
            Total: r.GetInt32(4)
        );
    }

    // ═══════════════════════════════════════
    // 헬스체크
    // ═══════════════════════════════════════

    public async Task<bool> PingAsync()
    {
        try
        {
            await using var conn = new NpgsqlConnection(_connStr);
            await conn.OpenAsync();
            await using var cmd = new NpgsqlCommand("SELECT 1", conn);
            await cmd.ExecuteScalarAsync();
            return true;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "PostgreSQL 연결 실패");
            return false;
        }
    }
}
