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

    public async Task<List<SentimentPoint>> GetSentimentHeatmapAsync(int days = 30)
    {
        var results = new List<SentimentPoint>();
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand($@"
            SELECT time_bucket('1 day', time) AS day,
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
            SELECT decision, wf_oos_sharpe, dsr_score, mc_prob_negative,
                   stress_passed, decided_at
            FROM go_stop_log
            ORDER BY decided_at DESC LIMIT 1", conn);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new GoStopDecision(
            Decision: r.GetString(0),
            WfSharpe: r.GetDouble(1),
            DsrScore: r.GetDouble(2),
            McProbNeg: r.GetDouble(3),
            StressPassed: r.GetBoolean(4),
            DecidedAt: r.GetDateTime(5)
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
