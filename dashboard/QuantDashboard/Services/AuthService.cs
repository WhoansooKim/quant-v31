using Npgsql;
using QuantDashboard.Models;

namespace QuantDashboard.Services;

public class AuthService
{
    private readonly string _connStr;
    private readonly ILogger<AuthService> _logger;

    public AuthService(string connectionString, ILogger<AuthService> logger)
    {
        _connStr = connectionString;
        _logger = logger;
    }

    public async Task<bool> ValidateAsync(string username, string password)
    {
        var user = await GetUserAsync(username);
        if (user is null) return false;

        return BCrypt.Net.BCrypt.Verify(password, user.PasswordHash);
    }

    public async Task<UserRecord?> GetUserAsync(string username)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(
            "SELECT id, username, password_hash, created_at FROM users WHERE username = @u",
            conn);
        cmd.Parameters.AddWithValue("u", username);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new UserRecord(
            Id: r.GetInt32(0),
            Username: r.GetString(1),
            PasswordHash: r.GetString(2),
            CreatedAt: r.GetDateTime(3)
        );
    }
}
