namespace QuantDashboard.Models;

// ─── 레짐 ───
public record RegimeState(
    string Regime,
    double BullProb,
    double SidewaysProb,
    double BearProb,
    double Confidence,
    string? PreviousRegime,
    bool IsTransition,
    DateTime DetectedAt
);

// ─── Kill Switch ───
public record KillSwitchState(
    string FromLevel,
    string ToLevel,
    double CurrentMdd,
    double PortfolioValue,
    double ExposureLimit,
    DateTime? CooldownUntil,
    DateTime EventTime
);

// ─── 포트폴리오 스냅샷 ───
public record DailySnapshot(
    DateTime Time,
    decimal TotalValue,
    decimal? CashValue,
    double? DailyReturn,
    double? CumulativeReturn,
    double? Sharpe,
    double MaxDrawdown,
    double? VolScale,
    string Regime,
    double? RegimeConfidence,
    string KillLevel,
    double? ExposureLimit
);

// ─── 거래 기록 ───
public record TradeRecord(
    long TradeId,
    string? OrderId,
    string Symbol,
    string Strategy,
    string Side,
    decimal Qty,
    decimal Price,
    string Regime,
    string KillLevel,
    DateTime ExecutedAt,
    bool IsPaper
);

// ─── 전략 성과 ───
public record StrategyPerf(
    DateTime Time,
    string Strategy,
    double DailyReturn,
    double Allocation,
    string Regime,
    int SignalCount,
    double? WinRate
);

// ─── 시그널 로그 ───
public record SignalRecord(
    DateTime Time,
    string Symbol,
    string Direction,
    double Strength,
    string Strategy,
    string Regime
);

// ─── 센티먼트 ───
public record SentimentPoint(
    DateTime Day,
    string Symbol,
    double AvgScore,
    int HeadlineCount
);

// ─── 백테스트 ───
public record BacktestRun(
    int RunId,
    string Name,
    string RunType,
    string Status,
    DateTime StartedAt,
    DateTime? FinishedAt,
    string? Summary
);

public record WalkForwardFoldResult(
    int FoldNum,
    DateTime TrainStart,
    DateTime TrainEnd,
    DateTime TestStart,
    DateTime TestEnd,
    double IsSharpe,
    double OosSharpe,
    double OosCagr,
    double OosMdd,
    double OosCalmar
);

public record MonteCarloResultRow(
    int NSims,
    double MedianCagr,
    double P5Cagr,
    double P95Cagr,
    double MedianSharpe,
    double P5Sharpe,
    double P95Sharpe,
    double MedianMdd,
    double ProbNegative,
    double ProbMddOver20
);

public record StressTestResultRow(
    string Scenario,
    DateTime PeriodStart,
    DateTime PeriodEnd,
    double TotalReturn,
    double MaxDrawdown,
    double Sharpe,
    bool KillTriggered,
    string KillLevelReached,
    double RegimeAccuracy,
    double FalsePositiveRate,
    int DetectionLagDays
);

public record DsrResultRow(
    double RawSharpe,
    double DsrScore,
    double DsrPvalue,
    int NTrials,
    double Skewness,
    double Kurtosis,
    bool Passed
);

public record GoStopDecision(
    string Decision,
    string? Criteria,
    string? Notes,
    string? DecidedBy,
    DateTime DecidedAt
);

// ─── 사용자 ───
public record UserRecord(
    int Id,
    string Username,
    string PasswordHash,
    DateTime CreatedAt
);

// ─── 시스템 상태 ───
public record SystemStatus(
    bool DbConnected,
    bool EngineHealthy,
    int BacktestRunCount,
    int SnapshotCount,
    int TradeCount,
    int SignalCount,
    string? LatestRegime,
    string? LatestKillLevel,
    string? LatestGoStop,
    DateTime? LatestSnapshotTime,
    DateTime? LatestRegimeTime,
    DateTime? LatestGoStopTime
);
