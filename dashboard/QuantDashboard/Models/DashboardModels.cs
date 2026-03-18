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

public record SentimentScoreRow(
    DateTime Time,
    string Symbol,
    double Score,
    string? Headline
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

// ─── 파이프라인 로그 ───
public record PipelineLogEntry(
    DateTime Time,
    string JobType,
    string Status,
    double? DurationSec,
    string? Details,
    string? ErrorMsg
);

// ─── 데이터 수집 현황 ───
public record DataCollectionStatus(
    DateTime? LatestDataDate,
    int ActiveSymbols,
    int RecentSymbols
);

// ─── 센티먼트 스캔 현황 ───
public record SentimentScanStatus(
    int Recent24hCount,
    DateTime? LastScanTime
);

// ─── 포트폴리오 보유 포지션 ───
public record PortfolioHolding(
    string Symbol, string Strategy, decimal NetQty,
    decimal AvgPrice, decimal TotalCost, DateTime LastTradeAt);

// ─── 전략 배분 현황 ───
public record StrategyAllocation(
    string Strategy, double Allocation, string Regime, DateTime Time);

// ─── 사용자 ───
public record UserRecord(
    int Id,
    string Username,
    string PasswordHash,
    DateTime CreatedAt,
    string? Email = null,
    string Role = "user",
    bool IsApproved = false
);

// ─── 레짐 전망 ───
public record RegimeForecast(
    [property: System.Text.Json.Serialization.JsonPropertyName("horizon_days")] int HorizonDays,
    [property: System.Text.Json.Serialization.JsonPropertyName("bull")] double Bull,
    [property: System.Text.Json.Serialization.JsonPropertyName("sideways")] double Sideways,
    [property: System.Text.Json.Serialization.JsonPropertyName("bear")] double Bear,
    [property: System.Text.Json.Serialization.JsonPropertyName("dominant")] string Dominant
);

// ─── 티커바 ───
public record TickerBarItem(
    string Symbol,
    double Price,
    double ChangePercent
);

// ─── 신호 분포 (5단계) ───
public record SignalDistribution(string Category, int Count);

// ─── Top/Bottom 종목 ───
public record RankedStock(string Symbol, string Sector, double Score, double ExpectedReturn, string Direction);

// ─── 섹터별 퀀트 스코어 ───
public record SectorScore(string Sector, double AvgScore, int Count);

// ─── 종목 상세 (16개 팩터) ───
public record SymbolDetail(
    string Symbol, string Sector, double? Price, double? Change1M, double? Change3M,
    double? Change6M, double? Change12M, double? PE, double? PB, double? PS,
    double? ROE, double? EpsGrowth, double? RevenueGrowth, double? DebtRatio,
    double? FCF, double? RSI, double? MACD, double? SMA50, double? SMA200,
    double? QuantScore, string? Signal);

// ─── SPY 벤치마크 포인트 ───
public record BenchmarkPoint(DateTime Time, double Value);

// ─── 시장 감성 (전체 평균) ───
public record MarketSentiment(double AvgScore, int PositiveCount, int NegativeCount, int NeutralCount, int Total);

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
