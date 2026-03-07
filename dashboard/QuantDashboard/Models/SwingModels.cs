namespace QuantDashboard.Models;

// ─── 스윙 시그널 ───
public record SwingSignal(
    long SignalId,
    DateTime Time,
    string Symbol,
    string SignalType,      // ENTRY / EXIT
    decimal? EntryPrice,
    decimal? StopLoss,
    decimal? TakeProfit,
    double? Return20dRank,
    bool TrendAligned,
    bool Breakout5d,
    bool VolumeSurge,
    string? ExitReason,
    long? PositionId,
    string Status,          // pending / approved / executed / rejected / expired
    DateTime? ApprovedAt,
    DateTime? ExecutedAt,
    int? LlmScore,          // AI score 1-10
    string? LlmAnalysis,   // AI analysis JSON
    DateTime? LlmAnalyzedAt
);

// ─── 스윙 포지션 ───
public record SwingPosition(
    long PositionId,
    string Symbol,
    string Side,
    decimal Qty,
    decimal EntryPrice,
    DateTime EntryTime,
    decimal? StopLoss,
    decimal? TakeProfit,
    decimal? CurrentPrice,
    decimal? UnrealizedPnl,
    double? UnrealizedPct,
    string Status,          // open / closed
    decimal? ExitPrice,
    DateTime? ExitTime,
    string? ExitReason,
    decimal? RealizedPnl,
    double? RealizedPct,
    int? HoldDays,
    long? SignalId,
    bool IsPaper,
    bool PartialExited = false,
    bool TrailingStopActive = false,
    decimal? HighWaterMark = null
);

// ─── 스윙 거래 ───
public record SwingTrade(
    long TradeId,
    long? PositionId,
    long? SignalId,
    string Symbol,
    string Side,
    decimal Qty,
    decimal Price,
    decimal? TotalAmount,
    string? OrderId,
    decimal? Commission,
    bool IsPaper,
    DateTime ExecutedAt
);

// ─── 포트폴리오 스냅샷 ───
public record SwingSnapshot(
    DateTime Time,
    decimal? TotalValueUsd,
    decimal? TotalValueKrw,
    decimal? CashUsd,
    decimal? InvestedUsd,
    decimal? DailyPnlUsd,
    double? DailyReturn,
    double? CumulativeReturn,
    double? MaxDrawdown,
    int OpenPositions,
    double? ExchangeRate
);

// ─── 런타임 설정 ───
public record SwingConfig(
    string Key,
    string Value,
    string Category,
    string? Description,
    DateTime UpdatedAt
);

// ─── 백테스트 결과 ───
public record SwingBacktestRun(
    long RunId,
    DateTime StartDate,
    DateTime EndDate,
    decimal? InitialCapital,
    decimal? FinalValue,
    double? TotalReturn,
    double? Cagr,
    double? MaxDrawdown,
    double? SharpeRatio,
    double? WinRate,
    int? TotalTrades,
    double? ProfitFactor,
    double? AvgHoldDays,
    DateTime CreatedAt
);

// ─── 백테스트 에퀴티 포인트 (Engine API JSON) ───
public record BacktestEquityPoint(
    string Date,
    double Value,
    double Cash,
    double Drawdown,
    int Positions
);

// ─── 백테스트 거래 엔트리 (Engine API JSON) ───
public record BacktestTradeEntry(
    string Date,
    string Symbol,
    string Side,
    double Qty,
    double Price,
    double Pnl,
    double PnlPct,
    string? Reason,
    int HoldDays
);

// ─── 백테스트 상세 (Engine API /backtest/results/{run_id}) ───
public class BacktestRunDetail
{
    public long RunId { get; set; }
    public string? StartDate { get; set; }
    public string? EndDate { get; set; }
    public double InitialCapital { get; set; }
    public double FinalValue { get; set; }
    public double TotalReturn { get; set; }
    public double Cagr { get; set; }
    public double MaxDrawdown { get; set; }
    public double SharpeRatio { get; set; }
    public double WinRate { get; set; }
    public int TotalTrades { get; set; }
    public double ProfitFactor { get; set; }
    public double AvgHoldDays { get; set; }
    public Dictionary<string, object?> Params { get; set; } = new();
    public List<BacktestEquityPoint> EquityCurve { get; set; } = new();
    public List<BacktestTradeEntry> TradesLog { get; set; } = new();
}

// ─── 백테스트 포트폴리오 홀딩 (팝업용) ───
public record BacktestPortfolioHolding(
    string Symbol,
    double Qty,
    double EntryPrice,
    string EntryDate
);

// ─── 파이프라인 로그 ───
public record SwingPipelineLog(
    long LogId,
    string StepName,
    string Status,
    double? ElapsedSec,
    string? Details,
    string? ErrorMsg,
    DateTime CreatedAt
);

// ─── 지표 요약 (Pipeline 팝업용) ───
public record SwingIndicatorRow(
    string Symbol,
    decimal? Close,
    decimal? Sma50,
    decimal? Sma200,
    double? Return20dRank,
    double? VolumeRatio,
    bool TrendAligned,
    bool VolumeSurge,
    DateTime Time
);

// ─── 유니버스 종목 ───
public record SwingUniverseItem(
    string Symbol,
    string? CompanyName,
    string? Sector,
    decimal? MarketCap,
    string? IndexMember
);

// ─── 심볼 디테일 (팝업용) ───
public record SwingSymbolDetail
{
    // 유니버스
    public string Symbol { get; init; } = "";
    public string? CompanyName { get; init; }
    public string? Sector { get; init; }
    public decimal? MarketCap { get; init; }
    public string? IndexMember { get; init; }

    // 가격 / 지표
    public decimal? Close { get; init; }
    public decimal? Sma50 { get; init; }
    public decimal? Sma200 { get; init; }
    public double? Return20d { get; init; }
    public double? Return20dRank { get; init; }
    public long? Volume { get; init; }
    public long? VolumeAvg20d { get; init; }
    public double? VolumeRatio { get; init; }
    public bool TrendAligned { get; init; }
    public bool Breakout5d { get; init; }
    public bool VolumeSurge { get; init; }

    // 수익률 (daily_prices 기반)
    public double? Return1M { get; init; }
    public double? Return3M { get; init; }
    public double? Return6M { get; init; }

    // 최근 시그널
    public SwingSignal? LatestSignal { get; init; }

    // 오픈 포지션
    public SwingPosition? OpenPosition { get; init; }

    // 진입 스코어 (계산)
    public double ScoreReturn { get; init; }
    public double ScoreTrend { get; init; }
    public double ScoreBreakout { get; init; }
    public double ScoreVolume { get; init; }
    public double ScoreTotal => ScoreReturn + ScoreTrend + ScoreBreakout + ScoreVolume;
}
