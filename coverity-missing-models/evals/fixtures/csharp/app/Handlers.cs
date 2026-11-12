// A catch handler is analyzed only when a callee's exceptions model says
// it throws. Each handler holds a null-dereference canary.
using System.IO;
using System.Resources;

public static class Handlers
{
    // ResourceManager.GetString's built-in exceptions model throws nothing,
    // so this handler is unreachable to the analysis: the canary is not reported.
    public static int FromResources(ResourceManager rm)
    {
        try
        {
            return rm.GetString("greeting").Length;
        }
        catch (MissingManifestResourceException)
        {
            string s = null;
            return s.Length;
        }
    }

    // File.ReadAllText's model throws IOException: the canary is reported.
    public static int FromFile(string path)
    {
        try
        {
            return File.ReadAllText(path).Length;
        }
        catch (IOException)
        {
            string s = null;
            return s.Length;
        }
    }

    // A static method, for the throw a user model adds (models/throw-static.cs).
    public static int FromPath(string path)
    {
        try
        {
            return Path.GetFileName(path).Length;
        }
        catch (System.InvalidOperationException)
        {
            string s = null;
            return s.Length;
        }
    }
}
