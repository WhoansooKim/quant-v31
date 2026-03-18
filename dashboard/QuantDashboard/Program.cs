using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using QuantDashboard.Components;
using QuantDashboard.Services;

// Npgsql: timestamptz → 로컬 시간(KST) 반환 (UTC 대신)
AppContext.SetSwitch("Npgsql.EnableLegacyTimestampBehavior", true);

var builder = WebApplication.CreateBuilder(args);

// ─── Blazor Server ───
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// ─── SignalR Circuit (연결 유지 설정 — 장시간 비활성 시에도 끊기지 않도록) ───
builder.Services.AddServerSideBlazor(options =>
{
    options.DetailedErrors = true;
    options.DisconnectedCircuitRetentionPeriod = TimeSpan.FromHours(12);
    options.DisconnectedCircuitMaxRetained = 5;
});

// ─── PostgreSQL 서비스 (Npgsql 직접) ───
var connStr = builder.Configuration.GetConnectionString("Default")!;

builder.Services.AddSingleton<PostgresService>(sp =>
    new PostgresService(connStr, sp.GetRequiredService<ILogger<PostgresService>>()));

builder.Services.AddSingleton<SwingService>(sp =>
    new SwingService(connStr, sp.GetRequiredService<ILogger<SwingService>>()));

builder.Services.AddSingleton<AuthService>(sp =>
    new AuthService(connStr, sp.GetRequiredService<ILogger<AuthService>>()));

// ─── gRPC Client (Python 엔진 통신) ───
builder.Services.AddSingleton<GrpcClient>();

// ─── HttpClient for Engine V4 API ───
builder.Services.AddHttpClient("Engine", client =>
{
    client.BaseAddress = new Uri(
        builder.Configuration["EngineApi:BaseUrl"] ?? "http://localhost:8001");
    client.Timeout = TimeSpan.FromSeconds(30);
});

// ─── SignalR Hub (실시간 푸시 — 장시간 연결 유지) ───
builder.Services.AddSignalR(o =>
{
    o.ClientTimeoutInterval = TimeSpan.FromHours(12);
    o.KeepAliveInterval = TimeSpan.FromSeconds(15);
    o.HandshakeTimeout = TimeSpan.FromSeconds(30);
});

// ─── Cookie Authentication ───
builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme)
    .AddCookie(o =>
    {
        o.LoginPath = "/login";
        o.LogoutPath = "/account/logout";
        o.ExpireTimeSpan = TimeSpan.FromHours(24);
        o.SlidingExpiration = true;
    });
builder.Services.AddAuthorization();
builder.Services.AddCascadingAuthenticationState();

var app = builder.Build();

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error", createScopeForErrors: true);
    app.UseHsts();
}
else
{
    app.UseDeveloperExceptionPage();
}

app.UseStaticFiles();
app.UseRouting();
app.UseAuthentication();
app.UseAuthorization();
app.UseAntiforgery();

// ─── Login / Logout Minimal API ───
app.MapPost("/account/login", async (HttpContext ctx, AuthService auth) =>
{
    var form = await ctx.Request.ReadFormAsync();
    var username = form["username"].ToString();
    var password = form["password"].ToString();

    var reason = await auth.ValidateWithReasonAsync(username, password);
    if (reason is null)
    {
        var user = await auth.GetUserAsync(username);
        var claims = new List<Claim>
        {
            new(ClaimTypes.Name, username),
            new(ClaimTypes.NameIdentifier, user!.Id.ToString()),
            new(ClaimTypes.Role, user.Role)
        };
        // Add page permissions as claims (admin gets all)
        if (user.Role != "admin")
        {
            var perms = await auth.GetRolePermissionsAsync(user.Role);
            foreach (var p in perms)
                claims.Add(new Claim("page_access", p));
        }
        var identity = new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme);
        await ctx.SignInAsync(
            CookieAuthenticationDefaults.AuthenticationScheme,
            new ClaimsPrincipal(identity));
        ctx.Response.Redirect("/");
    }
    else
    {
        ctx.Response.Redirect($"/login?error={reason}");
    }
}).AllowAnonymous();

app.MapPost("/account/register", async (HttpContext ctx, AuthService auth) =>
{
    var form = await ctx.Request.ReadFormAsync();
    var username = form["username"].ToString().Trim();
    var password = form["password"].ToString();
    var email = form["email"].ToString().Trim();

    if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password) || string.IsNullOrEmpty(email))
    {
        ctx.Response.Redirect("/register?error=required");
        return;
    }
    if (username.Length < 3 || password.Length < 6)
    {
        ctx.Response.Redirect("/register?error=length");
        return;
    }

    var (success, _) = await auth.RegisterAsync(username, password, email);
    if (success)
        ctx.Response.Redirect("/login?registered=1");
    else
        ctx.Response.Redirect("/register?error=exists");
}).AllowAnonymous();

app.MapPost("/account/logout", async (HttpContext ctx) =>
{
    await ctx.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
    ctx.Response.Redirect("/login");
}).AllowAnonymous();

// ─── SignalR 엔드포인트 ───
app.MapHub<RealtimeHub>("/hubs/realtime");

app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

app.Run();
