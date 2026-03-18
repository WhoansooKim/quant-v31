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
        if (!user.IsApproved) return false;

        return BCrypt.Net.BCrypt.Verify(password, user.PasswordHash);
    }

    /// <summary>Returns null if not approved (for login error differentiation).</summary>
    public async Task<string?> ValidateWithReasonAsync(string username, string password)
    {
        var user = await GetUserAsync(username);
        if (user is null) return "invalid";
        if (!BCrypt.Net.BCrypt.Verify(password, user.PasswordHash)) return "invalid";
        if (!user.IsApproved) return "not_approved";
        return null; // success
    }

    public async Task<UserRecord?> GetUserAsync(string username)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(
            "SELECT id, username, password_hash, created_at, email, role, is_approved FROM users WHERE username = @u",
            conn);
        cmd.Parameters.AddWithValue("u", username);

        await using var r = await cmd.ExecuteReaderAsync();
        if (!await r.ReadAsync()) return null;

        return new UserRecord(
            Id: r.GetInt32(0),
            Username: r.GetString(1),
            PasswordHash: r.GetString(2),
            CreatedAt: r.GetDateTime(3),
            Email: r.IsDBNull(4) ? null : r.GetString(4),
            Role: r.IsDBNull(5) ? "user" : r.GetString(5),
            IsApproved: !r.IsDBNull(6) && r.GetBoolean(6)
        );
    }

    // ─── Registration ───

    public async Task<(bool Success, string Message)> RegisterAsync(string username, string password, string email)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        // Check duplicate username
        await using var chk = new NpgsqlCommand(
            "SELECT COUNT(*) FROM users WHERE username = @u", conn);
        chk.Parameters.AddWithValue("u", username);
        var count = (long)(await chk.ExecuteScalarAsync())!;
        if (count > 0)
            return (false, "Username already exists");

        // Check duplicate email
        await using var chkEmail = new NpgsqlCommand(
            "SELECT COUNT(*) FROM users WHERE email = @e", conn);
        chkEmail.Parameters.AddWithValue("e", email);
        var emailCount = (long)(await chkEmail.ExecuteScalarAsync())!;
        if (emailCount > 0)
            return (false, "Email already registered");

        var hash = BCrypt.Net.BCrypt.HashPassword(password, 12);

        await using var cmd = new NpgsqlCommand(
            @"INSERT INTO users (username, password_hash, email, role, is_approved)
              VALUES (@u, @h, @e, 'user', false)", conn);
        cmd.Parameters.AddWithValue("u", username);
        cmd.Parameters.AddWithValue("h", hash);
        cmd.Parameters.AddWithValue("e", email);

        await cmd.ExecuteNonQueryAsync();
        _logger.LogInformation("New user registered: {Username} ({Email}) — awaiting approval", username, email);
        return (true, "Registration complete. Please wait for admin approval.");
    }

    // ─── Password Change ───

    public async Task<(bool Success, string Message)> ChangePasswordAsync(int userId, string currentPassword, string newPassword)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var getCmd = new NpgsqlCommand(
            "SELECT password_hash FROM users WHERE id = @id", conn);
        getCmd.Parameters.AddWithValue("id", userId);
        var hash = (string?)await getCmd.ExecuteScalarAsync();

        if (hash is null)
            return (false, "User not found");

        if (!BCrypt.Net.BCrypt.Verify(currentPassword, hash))
            return (false, "Current password is incorrect");

        var newHash = BCrypt.Net.BCrypt.HashPassword(newPassword, 12);

        await using var updCmd = new NpgsqlCommand(
            "UPDATE users SET password_hash = @h WHERE id = @id", conn);
        updCmd.Parameters.AddWithValue("h", newHash);
        updCmd.Parameters.AddWithValue("id", userId);
        await updCmd.ExecuteNonQueryAsync();

        _logger.LogInformation("Password changed for user ID {UserId}", userId);
        return (true, "Password changed successfully");
    }

    // ─── User Management (Admin) ───

    public async Task<List<UserRecord>> GetAllUsersAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(
            "SELECT id, username, password_hash, created_at, email, role, is_approved FROM users ORDER BY created_at DESC",
            conn);

        var list = new List<UserRecord>();
        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
        {
            list.Add(new UserRecord(
                Id: r.GetInt32(0),
                Username: r.GetString(1),
                PasswordHash: r.GetString(2),
                CreatedAt: r.GetDateTime(3),
                Email: r.IsDBNull(4) ? null : r.GetString(4),
                Role: r.IsDBNull(5) ? "user" : r.GetString(5),
                IsApproved: !r.IsDBNull(6) && r.GetBoolean(6)
            ));
        }
        return list;
    }

    public async Task<(bool Success, string Message)> AdminResetPasswordAsync(int userId, string newPassword)
    {
        if (newPassword.Length < 6)
            return (false, "Password must be at least 6 characters");

        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();

        var newHash = BCrypt.Net.BCrypt.HashPassword(newPassword, 12);

        await using var cmd = new NpgsqlCommand(
            "UPDATE users SET password_hash = @h WHERE id = @id", conn);
        cmd.Parameters.AddWithValue("h", newHash);
        cmd.Parameters.AddWithValue("id", userId);
        var rows = await cmd.ExecuteNonQueryAsync();

        if (rows > 0)
        {
            _logger.LogInformation("Admin reset password for user ID {UserId}", userId);
            return (true, "Password reset successfully");
        }
        return (false, "User not found");
    }

    public async Task<bool> ApproveUserAsync(int userId)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "UPDATE users SET is_approved = true WHERE id = @id", conn);
        cmd.Parameters.AddWithValue("id", userId);
        var rows = await cmd.ExecuteNonQueryAsync();
        if (rows > 0) _logger.LogInformation("User ID {UserId} approved", userId);
        return rows > 0;
    }

    public async Task<bool> RejectUserAsync(int userId)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "UPDATE users SET is_approved = false WHERE id = @id AND role != 'admin'", conn);
        cmd.Parameters.AddWithValue("id", userId);
        var rows = await cmd.ExecuteNonQueryAsync();
        if (rows > 0) _logger.LogInformation("User ID {UserId} rejected", userId);
        return rows > 0;
    }

    public async Task<bool> DeleteUserAsync(int userId)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "DELETE FROM users WHERE id = @id AND role != 'admin'", conn);
        cmd.Parameters.AddWithValue("id", userId);
        var rows = await cmd.ExecuteNonQueryAsync();
        if (rows > 0) _logger.LogInformation("User ID {UserId} deleted", userId);
        return rows > 0;
    }

    // ─── Role Change ───

    public async Task<bool> ChangeRoleAsync(int userId, string newRole)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "UPDATE users SET role = @r WHERE id = @id AND role != 'admin'", conn);
        cmd.Parameters.AddWithValue("r", newRole);
        cmd.Parameters.AddWithValue("id", userId);
        var rows = await cmd.ExecuteNonQueryAsync();
        if (rows > 0) _logger.LogInformation("User ID {UserId} role changed to {Role}", userId, newRole);
        return rows > 0;
    }

    // ─── Role Permissions ───

    /// <summary>Get all distinct roles from users table.</summary>
    public async Task<List<string>> GetRolesAsync()
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT DISTINCT role FROM users ORDER BY role", conn);
        var list = new List<string>();
        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync()) list.Add(r.GetString(0));
        // Ensure 'user' always exists
        if (!list.Contains("user")) list.Add("user");
        return list;
    }

    /// <summary>Get allowed pages for a role.</summary>
    public async Task<HashSet<string>> GetRolePermissionsAsync(string role)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT page_path FROM user_role_permissions WHERE role = @r", conn);
        cmd.Parameters.AddWithValue("r", role);
        var set = new HashSet<string>();
        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync()) set.Add(r.GetString(0));
        return set;
    }

    /// <summary>Rename a role (permissions + users).</summary>
    public async Task RenameRoleAsync(string oldRole, string newRole)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var tx = await conn.BeginTransactionAsync();

        // Update permissions table
        await using (var cmd = new NpgsqlCommand(
            "UPDATE user_role_permissions SET role = @new WHERE role = @old", conn, tx))
        {
            cmd.Parameters.AddWithValue("new", newRole);
            cmd.Parameters.AddWithValue("old", oldRole);
            await cmd.ExecuteNonQueryAsync();
        }

        // Update users table
        await using (var cmd = new NpgsqlCommand(
            "UPDATE users SET role = @new WHERE role = @old", conn, tx))
        {
            cmd.Parameters.AddWithValue("new", newRole);
            cmd.Parameters.AddWithValue("old", oldRole);
            await cmd.ExecuteNonQueryAsync();
        }

        await tx.CommitAsync();
        _logger.LogInformation("Role renamed: {Old} → {New}", oldRole, newRole);
    }

    /// <summary>Delete a role (permissions deleted, users fallback to 'user').</summary>
    public async Task DeleteRoleAsync(string role)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var tx = await conn.BeginTransactionAsync();

        // Delete permissions
        await using (var cmd = new NpgsqlCommand(
            "DELETE FROM user_role_permissions WHERE role = @r", conn, tx))
        {
            cmd.Parameters.AddWithValue("r", role);
            await cmd.ExecuteNonQueryAsync();
        }

        // Fallback users to 'user' role
        await using (var cmd = new NpgsqlCommand(
            "UPDATE users SET role = 'user' WHERE role = @r", conn, tx))
        {
            cmd.Parameters.AddWithValue("r", role);
            await cmd.ExecuteNonQueryAsync();
        }

        await tx.CommitAsync();
        _logger.LogInformation("Role '{Role}' deleted, users moved to 'user'", role);
    }

    /// <summary>Set allowed pages for a role (replace all).</summary>
    public async Task SetRolePermissionsAsync(string role, IEnumerable<string> pages)
    {
        await using var conn = new NpgsqlConnection(_connStr);
        await conn.OpenAsync();
        await using var tx = await conn.BeginTransactionAsync();

        // Delete existing
        await using (var del = new NpgsqlCommand(
            "DELETE FROM user_role_permissions WHERE role = @r", conn, tx))
        {
            del.Parameters.AddWithValue("r", role);
            await del.ExecuteNonQueryAsync();
        }

        // Insert new
        foreach (var page in pages)
        {
            await using var ins = new NpgsqlCommand(
                "INSERT INTO user_role_permissions (role, page_path) VALUES (@r, @p)", conn, tx);
            ins.Parameters.AddWithValue("r", role);
            ins.Parameters.AddWithValue("p", page);
            await ins.ExecuteNonQueryAsync();
        }

        await tx.CommitAsync();
        _logger.LogInformation("Role '{Role}' permissions updated: {Pages}", role, string.Join(", ", pages));
    }
}
