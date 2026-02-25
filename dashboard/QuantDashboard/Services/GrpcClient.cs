using Grpc.Net.Client;
using Quant;

namespace QuantDashboard.Services;

/// <summary>
/// Python 엔진 gRPC 클라이언트
/// RegimeService, PortfolioService, SignalService 통합
/// </summary>
public class GrpcClient : IDisposable
{
    private readonly GrpcChannel _channel;
    private readonly RegimeService.RegimeServiceClient _regime;
    private readonly PortfolioService.PortfolioServiceClient _portfolio;
    private readonly SignalService.SignalServiceClient _signals;
    private readonly ILogger<GrpcClient> _logger;

    public GrpcClient(IConfiguration config, ILogger<GrpcClient> logger)
    {
        _logger = logger;
        var url = config["GrpcUrl"] ?? "http://localhost:50051";
        _channel = GrpcChannel.ForAddress(url);
        _regime = new RegimeService.RegimeServiceClient(_channel);
        _portfolio = new PortfolioService.PortfolioServiceClient(_channel);
        _signals = new SignalService.SignalServiceClient(_channel);
        _logger.LogInformation("gRPC client connected to {Url}", url);
    }

    // ─── Regime ───

    public async Task<RegimeResponse?> GetRegimeAsync()
    {
        try
        {
            return await _regime.GetCurrentRegimeAsync(new Empty());
        }
        catch (Exception ex)
        {
            _logger.LogWarning("gRPC GetRegime failed: {Error}", ex.Message);
            return null;
        }
    }

    public async IAsyncEnumerable<RegimeResponse> StreamRegimeAsync(
        [System.Runtime.CompilerServices.EnumeratorCancellation]
        CancellationToken ct = default)
    {
        var call = _regime.StreamRegime(new Empty(), cancellationToken: ct);
        while (await call.ResponseStream.MoveNext(ct))
        {
            yield return call.ResponseStream.Current;
        }
    }

    // ─── Portfolio ───

    public async Task<SnapshotResponse?> GetSnapshotAsync()
    {
        try
        {
            return await _portfolio.GetSnapshotAsync(new Empty());
        }
        catch (Exception ex)
        {
            _logger.LogWarning("gRPC GetSnapshot failed: {Error}", ex.Message);
            return null;
        }
    }

    public async Task<PipelineStatus?> TriggerPipelineAsync()
    {
        try
        {
            return await _portfolio.TriggerPipelineAsync(new Empty());
        }
        catch (Exception ex)
        {
            _logger.LogWarning("gRPC TriggerPipeline failed: {Error}", ex.Message);
            return null;
        }
    }

    // ─── Signals ───

    public async Task<SignalList?> GetSignalsAsync(
        string strategy = "", int limit = 50)
    {
        try
        {
            var request = new SignalRequest
            {
                Strategy = strategy,
                Limit = limit
            };
            return await _signals.GetLatestSignalsAsync(request);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("gRPC GetSignals failed: {Error}", ex.Message);
            return null;
        }
    }

    // ─── Health ───

    public async Task<bool> IsConnectedAsync()
    {
        try
        {
            var regime = await _regime.GetCurrentRegimeAsync(new Empty());
            return regime != null;
        }
        catch
        {
            return false;
        }
    }

    public void Dispose()
    {
        _channel?.Dispose();
    }
}
