using QuantDashboard.Components;
using QuantDashboard.Services;

var builder = WebApplication.CreateBuilder(args);

// ─── Blazor Server ───
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// ─── PostgreSQL 서비스 (Npgsql 직접) ───
builder.Services.AddSingleton<PostgresService>(sp =>
    new PostgresService(
        builder.Configuration.GetConnectionString("Default")!,
        sp.GetRequiredService<ILogger<PostgresService>>()));

// ─── gRPC Client (Python 엔진 통신) ───
builder.Services.AddSingleton<GrpcClient>();

// ─── SignalR Hub (실시간 푸시) ───
builder.Services.AddSignalR();

var app = builder.Build();

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error", createScopeForErrors: true);
    app.UseHsts();
}

app.UseStaticFiles();
app.UseRouting();
app.UseAntiforgery();

// ─── SignalR 엔드포인트 ───
app.MapHub<RealtimeHub>("/hubs/realtime");

app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

app.Run();
