// A framework method's built-in model carries taint through it: the bytes
// a MemoryStream is constructed from taint the stream. Analyzed with
// --enable UNSAFE_DESERIALIZATION --distrust-filesystem --trust-network.
using System.IO;
using System.Runtime.Serialization.Formatters.Binary;

public static class Passthrough
{
    // File bytes -> stream -> deserialize. Reported with the built-in models;
    // lost when a user model of MemoryStream(byte[]) replaces them.
    public static object FromFile(string path)
    {
        byte[] bytes = File.ReadAllBytes(path);
        var stream = new MemoryStream(bytes);
        return new BinaryFormatter().Deserialize(stream);
    }

    // Bytes from a caller the analysis does not see. Nothing marks them
    // untrusted until a directive names this method as an entry point.
    public static object HandleRequest(byte[] body)
    {
        var stream = new MemoryStream(body);
        return new BinaryFormatter().Deserialize(stream);
    }
}
