// The tempting model: make every MemoryStream an untrusted source. It
// replaces the built-in model of the constructor, and with it the edge that
// carried the buffer's taint into the stream.
namespace System.IO
{
    public class MemoryStream
    {
        public MemoryStream(byte[] buffer)
        {
            Coverity.Primitives.Security.NetworkSource(this);
        }
    }
}
