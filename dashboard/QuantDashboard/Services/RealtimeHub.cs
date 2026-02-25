using Microsoft.AspNetCore.SignalR;

namespace QuantDashboard.Services;

/// <summary>
/// SignalR Hub — Python 엔진 → Blazor 대시보드 실시간 푸시
/// 이벤트: RegimeChanged, KillSwitchChanged, TradeExecuted, PipelineCompleted
/// </summary>
public class RealtimeHub : Hub
{
    public override async Task OnConnectedAsync()
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, "dashboard");
        await base.OnConnectedAsync();
    }

    /// <summary>레짐 전환 브로드캐스트</summary>
    public async Task BroadcastRegimeChange(string regime, double confidence)
    {
        await Clients.Group("dashboard").SendAsync(
            "RegimeChanged", regime, confidence);
    }

    /// <summary>Kill Switch 변경 브로드캐스트</summary>
    public async Task BroadcastKillSwitch(string level, double mdd)
    {
        await Clients.Group("dashboard").SendAsync(
            "KillSwitchChanged", level, mdd);
    }

    /// <summary>거래 체결 브로드캐스트</summary>
    public async Task BroadcastTradeExecuted(string symbol, string side,
        decimal qty, decimal price)
    {
        await Clients.Group("dashboard").SendAsync(
            "TradeExecuted", symbol, side, qty, price);
    }

    /// <summary>파이프라인 완료 브로드캐스트</summary>
    public async Task BroadcastPipelineCompleted(double pv, double mdd,
        int tradeCount)
    {
        await Clients.Group("dashboard").SendAsync(
            "PipelineCompleted", pv, mdd, tradeCount);
    }
}
