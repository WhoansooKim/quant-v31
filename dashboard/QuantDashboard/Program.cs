using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using QuantDashboard.Components;
using QuantDashboard.Services;

var builder = WebApplication.CreateBuilder(args);

// ─── Blazor Server ───
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// ─── PostgreSQL 서비스 (Npgsql 직접) ───
var connStr = builder.Configuration.GetConnectionString("Default")!;

builder.Services.AddSingleton<PostgresService>(sp =>
    new PostgresService(connStr, sp.GetRequiredService<ILogger<PostgresService>>()));

builder.Services.AddSingleton<AuthService>(sp =>
    new AuthService(connStr, sp.GetRequiredService<ILogger<AuthService>>()));

// ─── gRPC Client (Python 엔진 통신) ───
builder.Services.AddSingleton<GrpcClient>();

// ─── SignalR Hub (실시간 푸시) ───
builder.Services.AddSignalR();

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

    if (await auth.ValidateAsync(username, password))
    {
        var claims = new List<Claim>
        {
            new(ClaimTypes.Name, username)
        };
        var identity = new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme);
        await ctx.SignInAsync(
            CookieAuthenticationDefaults.AuthenticationScheme,
            new ClaimsPrincipal(identity));
        ctx.Response.Redirect("/");
    }
    else
    {
        ctx.Response.Redirect("/login?error=1");
    }
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
