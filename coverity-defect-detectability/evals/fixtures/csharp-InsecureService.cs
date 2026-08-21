using System;
using System.Data.SqlClient;
using System.Diagnostics;
using System.Net;
using System.Security.Cryptography;

namespace Demo
{
    class InsecureService
    {
        private const string ConnStr = "Server=localhost;Database=Test;User Id=sa;Password=Password123;";

        static void Main(string[] args)
        {
            string user = args.Length > 0 ? args[0] : "admin";

            var rng = new Random();
            var token = "tok-" + rng.Next();

            using (var conn = new SqlConnection(ConnStr))
            {
                conn.Open();
                var cmd = new SqlCommand($"SELECT * FROM Users WHERE Username = '{user}'", conn);
                var reader = cmd.ExecuteReader();
                while (reader.Read()) Console.WriteLine(reader["Username"]);
            }

            using var md5 = MD5.Create();
            var hash = md5.ComputeHash(System.Text.Encoding.UTF8.GetBytes("password"));
            Console.WriteLine(BitConverter.ToString(hash));

            ServicePointManager.ServerCertificateValidationCallback += (sender, certificate, chain, sslPolicyErrors) => true;

            Process.Start(new ProcessStartInfo("cmd.exe", "/c " + user) { UseShellExecute = false });
        }
    }
}
